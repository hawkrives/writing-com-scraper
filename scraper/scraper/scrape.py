from collections import deque, Counter
from pathlib import Path
import urllib.parse
import argparse
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

converter = html2text.HTML2Text()
converter.unicode_snob = True
converter.use_automatic_links = True
converter.body_width = 0


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


def get_meta(story_url: str, *, session: requests.session):
    body = session.get(story_url).text
    soup = BeautifulSoup(body, features="html.parser")

    story_title = soup.select_one('.proll').string
    story_title = re.sub(r'\s+', ' ', story_title)
    story_title = story_title.strip()

    story_author = soup.select_one('.shadowBoxTop a[title^=Username]').text

    meta_items = soup.select('.mainLineBorderTop > div > div[style] > div')
    rating, chapter_count, created, updated = [e.get_text() for e in meta_items]

    rating = rating.replace('Intro Rated:', '').strip()
    chapter_count = int(re.sub(r'[^0-9]', '', chapter_count))

    date_created = parse_writing_time(created)
    date_updated = parse_writing_time(updated)

    return {
        'title': story_title,
        'author': story_author,
        'rating': rating,
        'chapter_count': chapter_count,
        'date_created': date_created,
        'date_updated': date_updated,
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
        print('Login failed')
        sys.exit(1)


seen_urls_counter = Counter()
def sleep_for_url(url: str):
    seen_urls_counter[url] += 1
    n = seen_urls_counter[url]
    amount = 30 + (2 ** n) + (random.randint(0, 1000) / 1000)
    print('sleeping for', amount, 'seconds')
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


def scrape_chapter(url: str, *, chapter_id: str, session: requests.session):
    """
    input: url
    output: {title: str, content: markdown_str, choices: list({text, id})}
    """
    req = session.get(url)
    body = req.text

    interactive_warning = '<title>Interactive Stories Are Temporarily Unavailable</title>'
    while interactive_warning in body:
        sleep_for_url(url)
        cache_backend.delete_url(url)
        req = session.get(url)
        body = req.text

    soup = BeautifulSoup(body, features="html.parser")

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

    content_soup = soup.select_one('.norm')

    chapter_heading = content_soup.select_one('span[title^=Created]')

    chapter_title = chapter_heading.select_one('b').string

    chapter_date = chapter_heading['title'].replace('Created: ', '')

    # Find chapter author
    chapter_author = content_soup.select_one('i + .noselect > [title^=Username]')
    if chapter_author:
        chapter_author = chapter_author.string
    else:
        chapter_author = 'Unknown'

    # Find story content
    chapter_body_soup = content_soup.select_one('.KonaBody')

    for anchor in chapter_body_soup.select('a'):
        if anchor.get('href', None) is None:
            continue
        anchor['href'] = clean_redirect_url(anchor['href'])

    chapter_body = str(chapter_body_soup)
    chapter_body = clean_chapter_body(chapter_body)

    # Find chapter links
    chapter_link_elements = content_soup.select('div > div > p[align=left]:has(> a)')
    chapter_links = [{
        'id': chapter_id + str(index + 1),
        'text': p.select_one('a').get_text().strip(),
        'type': 'blank' if any([b.string == '*' for b in p.select('b')]) else 'chapter'
    } for index, p in enumerate(chapter_link_elements)]

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

    if not req.from_cache:
        # print('sleep 5')
        time.sleep(5)

    return {
        'id': chapter_id,
        'title': chapter_title,
        'author': chapter_author,
        'content': chapter_body,
        'choices': chapter_links,
        'date': chapter_date,
        'is_ending': False,
    }


def scrape_story(story_index_url: str, *, starting_point: str, session: requests.session):
    chapters_to_scrape = deque(starting_point)
    scraped_chapters = set()

    while True:
        try:
            chapter_id = chapters_to_scrape.popleft()
        except IndexError:
            # print('chapter downloading complete!')
            break

        chapter_url = story_index_url + 'map/' + chapter_id
        # print(chapter_url)

        chapter = scrape_chapter(chapter_url, chapter_id=chapter_id, session=session)
        scraped_chapters.add(chapter['id'])
        yield chapter

        for choice in chapter['choices']:
            if choice['type'] == 'chapter':
                chapters_to_scrape.append(choice['id'])

        print(f"{len(chapters_to_scrape)}|{len(scraped_chapters)} {'-'.join([*chapter['id']])}")


def clean_story_url(story_url):
    story_url = story_url.replace('/interact.php/', '/interact')
    story_url = story_url.replace('//writing.com/', '//www.writing.com/')

    if not "/interact/" in story_url:
        print("Invalid URL. Only interactive stories are supported at this time.")
        sys.exit(1)

    if "/map/" in story_url:
        print("Invalid URL. You must pass the overview page at this time.")
        sys.exit(1)

    if not story_url.endswith('/'):
        story_url += '/'

    return story_url


def args():
    parser = argparse.ArgumentParser(description='Download a story from writing.com')
    parser.add_argument('story_url', type=str,
                        help='the story URL to download')
    parser.add_argument('starting_point', type=str, nargs='?', default='1',
                        help='the chapter to start at (eg, 15115)')

    parsed = parser.parse_args()

    parsed.story_url = clean_story_url(parsed.story_url)
    parsed.starting_point = parsed.starting_point.split(',')

    return parsed


def print_chapter(chapter):
    print()
    print('-' * 72)
    print()
    print(f"> created: {chapter['date']}")
    print(f"> id({len(chapter['id'])}): {'-'.join([*chapter['id']])}")
    print(f"> title: {chapter['title']}")
    print()
    print(chapter['content'])
    print()
    if not chapter['is_ending']:
        print('-' * 72)
        print()
        for i, choice in enumerate(chapter['choices']):
            text = choice['text']
            if choice['type'] == 'blank':
                text = '* ' + text
            print(f'{i+1}) {text}')
        print()
    print('-' * 72)
    print()


def main():
    global cache_backend

    arguments = args()
    story_url = arguments.story_url
    starting_point = arguments.starting_point

    print(f'downloading {story_url}, starting at {starting_point}')

    story_id = get_id(story_url)
    folder = Path('.') / f'{story_id}'
    folder.mkdir(parents=True, exist_ok=True)

    cache_backend = requests_cache.backends.sqlite.DbCache(location=(folder / 'cache').as_posix())
    s = requests_cache.CachedSession(backend=cache_backend)

    log_in(session=s, username=username, password=password)

    story_meta = get_meta(story_url, session=s)
    print(story_meta)

    with open(folder / f'meta.json', 'w', encoding='utf-8') as outfile:
        json.dump(story_meta, outfile, sort_keys=True, indent=4)
        outfile.write('\n')

    for chapter in scrape_story(story_url, starting_point=starting_point, session=s):
        # print(chapter)
        # print_chapter(chapter)
        pass
        with open(folder / f'{chapter["id"]}.json', 'w', encoding='utf-8') as outfile:
            json.dump(chapter, outfile, sort_keys=True, indent=4)
            outfile.write('\n')


if __name__ == '__main__':
    main()
