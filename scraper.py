# -*- coding: utf-8 -*-

# Writing.com scraper script, for the archival of Writing.com stories.
# Created by Andrew Morgan (2015, https://github.com/anoadragon453/Writing.com-Story-Scraper)
# Updated by Hawken Rives (2018, https://github.com/hawkrives/writing-com-scraper)

from bs4 import BeautifulSoup
import os
import html2text
import re
from yattag import Doc

# Define global variables
br = mechanize.Browser()
current_working_directory = os.path.dirname(os.path.realpath(__file__))

def formatText(string_to_format):
    string_to_format = html2text.html2text(string_to_format.replace("<br />","\n").decode('utf8', 'ignore'))
    return string_to_format

def scrape(url,story_title):
    response = br.open(url)
    page_source = response.read()

    # Find chapter title
    chapter_title_section = page_source.find('<b>Chapter')
    chapter_title_begin = page_source.find('<big>', chapter_title_section)
    chapter_title_end = page_source.find('</big>', chapter_title_begin)
    chapter_title = formatText(page_source[chapter_title_begin+5:chapter_title_end])
    #print "\nChapter Title is %s" % chapter_title

    # Find chapter author
    chapter_author_location = page_source.find('&nbsp;<i>an addition by: </i>')
    chapter_author_section = page_source.find('<a title="Username:',chapter_author_location)+19
    chapter_author_end = page_source.find('Member Since:', chapter_author_section)-1
    if chapter_author_section == 18:
        chapter_author_section = page_source.find('/user_id/',chapter_author_location)+9
        chapter_author_end = page_source.find('">',chapter_author_section)
    chapter_author = formatText(page_source[chapter_author_section:chapter_author_end])
    #print "\nChapter author is %s" % chapter_author

    # Find story content
    chapter_body_section = page_source.find('<div class="KonaBody">')
    chapter_body_end = page_source.find('</div>',chapter_body_section)
    chapter_body = formatText(page_source[chapter_body_section+22:chapter_body_end])
    #print "\nChapter Body is %s" % chapter_body

    # Find chapter links
    title_array = []
    next_chapter_title_section = page_source.find('<big><b>You have the following choice')
    while page_source.find('</a>',chapter_title_section) != -1:
        next_chapter_title_start = page_source.find('">',next_chapter_title_section) + 2
        next_chapter_title = page_source[next_chapter_title_start:page_source.find('</a>',next_chapter_title_section)]
        if next_chapter_title_start > page_source.find('<div id="end_of_choices"></div>', next_chapter_title_section):
            break
        if '<b>*</b>' in page_source[next_chapter_title_start:page_source.find('">',next_chapter_title_start)]:
            next_chapter_title+=" *"
        title_array.append(formatText(next_chapter_title))
        next_chapter_title_section = page_source.find('</a>',next_chapter_title_section) + 5

    # Generate HTML chapter file
    current_chapter = url[url.find('/map/')+5:]

    # Set up yattag
    doc, tag, text = Doc().tagtext()

    doc.asis('<!DOCTYPE html>')
    with tag('html'):
        with tag('body'):
            with tag('h1'):
                text(chapter_title)
            with tag('h4'):
                with tag('i'):
                    text("Authored by: "+chapter_author)
            with tag('p', id = 'main'):
                text(chapter_body)
            for title in title_array:
                title_chapter_number = title_array.index(title)+1
                with tag('p', id = 'main'):
                    with tag('a', href=str(current_chapter)+str(title_chapter_number)+".html"):
                        text(title)
        if current_chapter != '1':
            with tag('p', id = 'main'):
                with tag('a', href=current_chapter[:-1]+".html"):
                    text("-Back-")

    # Write generated HTML to a file
    html_path = current_working_directory + "/" + story_title
    if not os.path.isdir(html_path):
        os.mkdir( html_path, 0755 );
    #print "DEBUG: Trying to open "+current_working_directory+"/"+str(story_title)+"/"+str(current_chapter)+".html"
    html_file = open(current_working_directory+"/"+story_title+"/"+str(current_chapter)+".html", "w")
    html_file.write(doc.getvalue().encode('utf-8'))
    html_file.close()

    # Scrape every link
    for title in title_array:
        print "SCRAPING: "+url+str(title_array.index(title)+1)
        if title.strip()[-1] != "*":
            scrape(url+str(title_array.index(title)+1),story_title)

def login():
    print "Starting login process..."

    url = "http://www.writing.com/main/login.php"
    br.set_handle_robots(False) # ignore robots
    br.open(url)

    br.form = list(br.forms())[2]

    # Grab User credentials
    print "\nPlease enter a Writing.com username (Necessary for viewing Interactive Stories):"
    user_uname = raw_input()
    print "\nEnter password:"
    user_password = getpass()

    uname_control = br.form.find_control("login_username")
    uname_control.value = user_uname

    password_control = br.form.find_control("login_password")
    password_control.value = user_password

    print "Attempting login..."

    response = br.submit()

    # Check for successful login
    login_check = 0;
    for link in br.links():
        if "Logout" in link.text:
            login_check = 1
    if login_check == 1:
        print "\nSuccessfully logged in!\n"
        grabURL();
    else:
        print "\nLogin Failed. Retrying...\n"
        login();

def grabURL():
    print "Welcome to the Writing.com Scraper!"
    print "At the moment, this script only supports interactive stories.\n"
    url = raw_input("Please enter the story URL: ")
    url = url.strip()

    if not "http://" in url:
        url = "http://" + url

    if not "interact" in url:
        print "URL invalid. Please note only interactive stories are supported."
        return;

    if not "/map/" in url:
        if not url.endswith('/'):
            url+='/'

        url = url + "map/1"

    story_title = url[url.find("/item_id/")+9:url.find("/map/")]

    scrape(url,story_title)

login()
