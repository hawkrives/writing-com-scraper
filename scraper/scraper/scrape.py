from collections import deque, Counter
import urllib.parse
import random
import time
import sys
import os
import re
from bs4 import BeautifulSoup
import requests_cache
import html2text
import requests

username = os.getenv('WRITINGCOM_USERNAME')
password = os.getenv('WRITINGCOM_PASSWORD')

cache_backend = requests_cache.backends.sqlite.DbCache(location='writing.com_cache')

converter = html2text.HTML2Text()
converter.unicode_snob = True
converter.body_width = 0


def html_to_text(html: str):
    return converter.handle(html)


def get_title(story_url: str, *, session: requests.session):
    body = session.get(story_url).text
    soup = BeautifulSoup(body, features="html.parser")
    return soup.select_one('.proll').string


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
            'is_ending': True,
        }

    content_soup = soup.select_one('.norm')

    chapter_title = content_soup.select_one('span[title^=Created] b').string

    # Find chapter author
    chapter_author = content_soup.select_one('i + .noselect > [title^=Username]')
    if chapter_author:
        chapter_author = chapter_author.string
    else:
        chapter_author = 'Unknown'

    # Find story content
    chapter_body_soup = content_soup.select_one('.KonaBody')
    chapter_body = html_to_text(str(chapter_body_soup))

    # Find chapter links
    chapter_links = [{'id': chapter_id + str(index + 1), 'text': p.select_one('a').string, 'type': 'blank' if any([b.string == '*' for b in p.select('b')]) else 'chapter'}
                     for index, p in enumerate(content_soup.select('div > div > p[align=left]:has(> a)'))]

    if not req.from_cache:
        time.sleep(15)

    return {
        'id': chapter_id,
        'title': chapter_title,
        'author': chapter_author,
        'content': chapter_body,
        'choices': chapter_links,
        'is_ending': False,
    }


def scrape_story(story_index_url: str, *, session: requests.session):
    chapters_to_scrape = deque(['1'])
    scraped_chapters = set()

    while True:
        try:
            chapter_id = chapters_to_scrape.popleft()
        except IndexError:
            print('chapter downloading complete!')
            break

        chapter_url = story_index_url + 'map/' + chapter_id
        print(chapter_url)

        chapter = scrape_chapter(chapter_url, chapter_id=chapter_id, session=session)
        scraped_chapters.add(chapter['id'])
        yield chapter

        for choice in chapter['choices']:
            if choice['type'] == 'chapter':
                chapters_to_scrape.append(choice['id'])

        # print('queue:', chapters_to_scrape)
        print('queue size:', len(chapters_to_scrape))
        print('completed size:', len(scraped_chapters))
        print()


def main(story_url):
    print(story_url)
    if not "/interact/" in story_url:
        print("Invalid URL. Only interactive stories are supported at this time.")
        sys.exit(1)

    if "/map/" in story_url:
        print("Invalid URL. You must pass the overview page at this time.")
        sys.exit(1)

    if not story_url.endswith('/'):
        story_url += '/'

    story_id = get_id(story_url)

    s = requests_cache.CachedSession(backend=cache_backend)
    log_in(session=s, username=username, password=password)

    story_title = get_title(story_url, session=s)

    for chapter in scrape_story(story_url, session=s):
        print(chapter)
        print()


if __name__ == '__main__':
    story_url = sys.argv[1]
    main(story_url)
