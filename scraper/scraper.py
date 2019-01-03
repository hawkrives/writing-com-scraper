import urllib.parse
import collections
import contextlib
import threading
import argparse
import hashlib
import pathlib
import random
import json
import time
import sys
import os
import re
from bs4 import BeautifulSoup
import requests_cache
import html2text
import pendulum
import requests

username = os.getenv('WRITINGCOM_USERNAME')
password = os.getenv('WRITINGCOM_PASSWORD')

cache_backend = None

requests_lock = threading.Lock()

seen_urls_counter = collections.Counter()

converter = html2text.HTML2Text()
converter.unicode_snob = True
converter.use_automatic_links = True
converter.body_width = 0


def stderr(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)


def html_to_text(html: str):
    return converter.handle(html)


def parse_writing_time(ts: str):
    # remove the prefix
    ts = re.sub(r'^.*: ', '', ts)

    # remove the " at "
    ts = ts.replace(' at ', ' ')

    # uppercase the meridian for pendulum
    ts = ts.replace('am', 'AM').replace('pm', 'PM')

    # parse (eg. "October 7th 2007, 5:27PM")
    timestamp = pendulum.from_format(ts, 'MMMM Do, YYYY h:mmA')

    # and isoformat for return
    return timestamp.isoformat()


def get_meta(story_url: str, *, session: requests.session, stale_ok: bool = False):
    if not stale_ok:
        # ensure we get a fresh response
        cache_backend.delete_url(story_url)

    response = session.get(story_url)
    body = response.text
    soup = BeautifulSoup(body, features="lxml")

    story_title = soup.select_one('.proll').string
    story_title = re.sub(r'\s+', ' ', story_title)
    story_title = story_title.strip()

    story_id = get_id(story_url)

    story_author = soup.select_one('.shadowBoxTop a[title^=Username]').text

    meta_items = soup.select('.mainLineBorderTop > div > div[style] > div')
    rating, chapter_count, created, updated = [e.get_text() for e in meta_items]

    rating = rating.replace('Intro Rated:', '').strip()
    chapter_count = int(re.sub(r'[^0-9]', '', chapter_count))

    date_created = parse_writing_time(created)
    date_updated = parse_writing_time(updated)

    return {
        'url': response.url,
        'id': story_id,
        'title': story_title,
        'author': story_author,
        'rating': rating,
        'chapter_count': chapter_count,
        'date_created': date_created,
        'date_updated': date_updated,
        'date_fetched': pendulum.now().isoformat(),
    }


def get_id(story_url: str):
    """ extracts the Story ID from an URL
    """
    parts = urllib.parse.urlsplit(story_url)
    *_, slug, _ = parts.path.split('/')
    idnum, *_ = slug.split('-')
    return int(idnum)


def log_in(*, session, username, password):
    url = "https://www.writing.com/main/login.php"
    data = {'login_username': username, 'login_password': password}

    cache_backend.delete_url(url)
    resp = session.post(url, data=data)

    if 'Logout' not in resp.text:
        stderr('Login failed')
        sys.exit(1)


def sleep_for_url(url: str):
    seen_urls_counter[url] += 1
    n = seen_urls_counter[url]
    amount = 30 + (2 ** n) + (random.randint(0, 1000) / 1000)
    stderr('sleeping for', amount, 'seconds')
    time.sleep(amount)


def clean_redirect_url(href: str):
    parts = urllib.parse.urlsplit(href)
    if parts.path == '/main/redirect.php':
        query = urllib.parse.parse_qs(parts.query)
        return query['redirect_url'][0]
    return href


def clean_chapter_body(content: str):
    content = re.sub(r'<br ?/?>', r'<br /><br />', content)
    content = html_to_text(content)
    content = content.strip()
    content = re.sub(r' +', ' ', content)
    content = re.sub(r'\n\s*(\n\s*)+', '\n\n', content)
    return content


def fetch_page(*, url: str, session: requests.session):
    req = session.get(url)
    body = req.text

    if not req.from_cache:
        # stderr('sleep 5')
        time.sleep(5)

    interactive_warning = '<title>Interactive Stories Are Temporarily Unavailable</title>'
    while interactive_warning in body:
        sleep_for_url(url)
        cache_backend.delete_url(url)
        req = session.get(url)
        body = req.text

    return body


def process_chapter(*, body: str, chapter_id: str):
    # fix invalid HTML from the abbreviated chapter title
    body = body.replace('&#.', '&amp;#.')

    soup = BeautifulSoup(body, features="lxml")

    debugging = False
    if debugging:
        for tag in soup.select('meta, script, style, select, input, form, .noSelect, #Page_Top_Wrapper, #Left_Column_Wrapper, .noPrint, #Footer_Wrapper'):
            tag.decompose()

        for attr in ['onclick', 'style', 'onkeyup', 'onkeydown', 'onmouseover', 'onmouseup', 'onmouseout', 'onmousedown', 'oncontextmenu', 'ontouchstart', 'ontouchend', 'onfocus', 'onchange']:
            for tag in soup.select(f'[{attr}]'):
                tag[attr] = ''

        for tag in soup.select('[href^=javascript]'):
            tag['href'] = ''

        print(soup.prettify())

    ending_chapter = soup.select_one('.shadowBox > div:nth-of-type(1) > big > b')

    if ending_chapter:
        return {
            'id': chapter_id,
            'title': 'Continue this story…',
            'author': 'Writing.com',
            'content': "Congratulations! You have reached the end of an existing storyline.",
            'choices': [],
            'date': None,
            'is_ending': True,
        }

    content_soup = soup.select_one('#Content_Column_Inner')

    try:
        chapter_heading = content_soup.select_one('span[title^=Created]')

        chapter_title = chapter_heading.select_one('b').string

        chapter_date = chapter_heading['title'].replace('Created: ', '')

        # Find chapter author
        chapter_author = content_soup.select_one('i + .noselect > [title^=Username]')
        if chapter_author:
            chapter_author = chapter_author.string
        else:
            chapter_author = 'Unknown'
    except AttributeError as exception:
        stderr(url)
        print(content_soup)
        stderr(exception, file=sys.stderr)

    # Find story content
    chapter_body_soup = content_soup.select_one('.KonaBody')

    for anchor in chapter_body_soup.select('a'):
        if anchor.get('href', None) is None:
            continue
        anchor['href'] = clean_redirect_url(anchor['href'])

    chapter_body = str(chapter_body_soup)
    chapter_body = clean_chapter_body(chapter_body)

    # Find chapter links
    chapter_link_elements = content_soup.select('div > div > div[style] ~ p[align=left]:has(> a)')
    chapter_links = []
    for index, p in enumerate(chapter_link_elements):
        anchor = p.select_one('a')
        choice_type = 'blank' if any([b.string == '*' for b in p.select('b')]) else 'chapter'
        link = {
            'id': chapter_id + str(index + 1),
            'text': anchor.get_text().strip(),
            'type': choice_type,
        }
        chapter_links.append(link)

    if len(chapter_links) is 0:
        return {
            'id': chapter_id,
            'title': chapter_title,
            'author': chapter_author,
            'content': chapter_body,
            'choices': chapter_links,
            'date': chapter_date,
            'is_ending': True,
        }

    return {
        'id': chapter_id,
        'title': chapter_title,
        'author': chapter_author,
        'content': chapter_body,
        'choices': chapter_links,
        'date': chapter_date,
        'is_ending': False,
    }


def scrape_chapter(url: str, *, chapter_id: str, session: requests.session):
    with requests_lock:
        body = fetch_page(url=url, session=session)

    return process_chapter(body=body, chapter_id=chapter_id)


def scrape_story(story_index_url: str, *, starting_point: str, session: requests.session):
    chapters_to_scrape = collections.deque(starting_point)
    scraped_chapters = set()

    while True:
        try:
            chapter_id = chapters_to_scrape.popleft()
        except IndexError:
            # chapter downloading complete!
            break

        story_index_url = story_index_url + '/' if not story_index_url.endswith('/') else story_index_url

        chapter_url = story_index_url + 'map/' + chapter_id

        chapter = scrape_chapter(chapter_url, chapter_id=chapter_id, session=session)
        scraped_chapters.add(chapter['id'])
        yield chapter, len(chapters_to_scrape), len(scraped_chapters)

        for choice in chapter['choices']:
            if choice['type'] == 'chapter':
                chapters_to_scrape.append(choice['id'])


def is_integer(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


def clean_story_url(story_url):
    if is_integer(story_url):
        return f'https://writing.com/main/interact/item_id/{story_url}/'

    story_url = story_url.replace('/interact.php/', '/interact')
    story_url = story_url.replace('//writing.com/', '//www.writing.com/')

    if not "/interact/" in story_url:
        stderr("Invalid URL. Only interactive stories are supported at this time.")
        sys.exit(1)

    if "/map/" in story_url:
        stderr("Invalid URL. You must pass the overview page at this time.")
        sys.exit(1)

    if not story_url.endswith('/'):
        story_url += '/'

    return story_url


def get_args():
    parser = argparse.ArgumentParser(description='Download a story from writing.com')
    parser.add_argument('story_url', type=str,
                        help='the story URL to download')
    parser.add_argument('starting_point', type=str, nargs='?', default='1',
                        help='the chapter to start at (eg, 15115)')
    parser.add_argument('--debug', action='store_true',
                        help='enter debug mode')

    parsed = parser.parse_args()

    parsed.story_url = clean_story_url(parsed.story_url)
    parsed.starting_point = parsed.starting_point.split(',')

    return parsed


def main():
    global cache_backend

    arguments = get_args()
    story_url = arguments.story_url
    starting_point = arguments.starting_point

    stderr(f'downloading {story_url}, starting at {starting_point}')

    story_id = get_id(story_url)
    folder = pathlib.Path('.') / 'archive' / f'{story_id}'
    folder.mkdir(parents=True, exist_ok=True)

    chapters_dir = folder / 'chapters'
    chapters_dir.mkdir(parents=True, exist_ok=True)

    cache_backend = requests_cache.backends.sqlite.DbCache(location=(folder / 'cache').as_posix())
    s = requests_cache.CachedSession(backend=cache_backend)

    if not arguments.debug:
        start = time.perf_counter()
        log_in(session=s, username=username, password=password)
        stderr(f'login took {time.perf_counter() - start:0.02}')

    start = time.perf_counter()
    story_meta = get_meta(story_url, session=s, stale_ok=arguments.debug)
    # be sure to update with the canonical url
    story_url = story_meta['url']
    stderr(json.dumps(story_meta, sort_keys=True, indent=4))
    stderr(f'meta fetch took {time.perf_counter() - start:0.02}')

    story_filename = "".join([c if c.isalpha() or c.isdigit() or c==' ' else '_' for c in story_meta['title']]).strip()
    chapter_count_width = len(str(story_meta['chapter_count']))

    with open(folder / f'0-{story_filename}', 'w') as outfile:
        outfile.write('\n')

    with open(folder / f'meta.json', 'w', encoding='utf-8') as outfile:
        json.dump(story_meta, outfile, sort_keys=True, indent='\t')
        outfile.write('\n')

    for chapter, pending_count, completed_count in scrape_story(story_url, starting_point=starting_point, session=s):
        # print_chapter(chapter)
        pending_count = str(pending_count).zfill(chapter_count_width)
        completed_count = str(completed_count).zfill(chapter_count_width)
        chapter_count = story_meta['chapter_count']
        pretty_chapter_id = '-'.join([*chapter['id']])
        stderr(f"{pending_count} {completed_count}/{chapter_count} {pretty_chapter_id}")
        chapter_filename = hashlib.sha256(chapter["id"].encode()).hexdigest()
        with open(chapters_dir / f'{chapter_filename}.json', 'w', encoding='utf-8') as outfile:
            json.dump(chapter, outfile, sort_keys=True, indent='\t')
            outfile.write('\n')


if __name__ == '__main__':
    main()
