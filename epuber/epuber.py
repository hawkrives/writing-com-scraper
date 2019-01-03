import argparse
import hashlib
import pathlib
import json
from ebooklib import epub
import markdown2


def hyphenate_id(idstr: str, ch = '-'):
	return ch.join([*idstr])


def nav_links(last_id):
	yield '<p>'
	yield 'Jump to: '
	if last_id:
		yield f'<a href="{last_id}.xhtml">Parent</a>'
		yield f' | '
	yield f'<a href="nav.xhtml">Outline</a>'
	yield '</p>'


def chapter_heading(chapter):
	yield f'<p>Path: {hyphenate_id(chapter["id"])}</p>'
	yield f'<h1>{chapter["title"]}</h1>'
	yield f'<p>by <em>{chapter["author"]}</em> on {chapter["date"]}</p>'


def choice_links(choices):
	if not choices:
		return '<p>This chapter has no choices.</p>'

	yield '<h2>Choices</h2>'
	yield '<ol>'
	for choice in choices:
		yield '<li>'

		if choice['type'] == 'chapter':
			yield f'<a href="./{choice["id"]}.xhtml">'

		if choice['type'] == 'blank':
			yield '* '

		yield choice["text"]

		if choice['type'] == 'chapter':
			yield '</a>'

		yield '</li>'
	yield '</ol>'


def generate_chapter(chapter):
	last_id = chapter["id"][:-1]

	yield from nav_links(last_id)
	yield from chapter_heading(chapter)
	yield chapter['content']
	yield from choice_links(chapter['choices'])
	yield from nav_links(last_id)


def create_chapter_content(chapter):
	return ''.join(generate_chapter(chapter))


def generate_book(story_meta, chapters):
	print('generating epub')
	book = epub.EpubBook()

	# set metadata
	book.set_identifier(story_meta['url'])
	book.set_title(story_meta['title'])
	book.set_language('en-US')

	book.add_author(story_meta['author'])

	for author in set([c['author'] for c in chapters]):
		book.add_author(author, uid='coauthor')

	# define CSS style
	style = '''
body {
	font-family: -apple-system, Helvetica Neue, sans-serif;
	font-weight: normal;
}
'''.strip()
	nav_css = epub.EpubItem(uid="styles", file_name="style/stylesheet.css", media_type="text/css", content=style)

	# create chapter
	epub_chapters = []
	for chapter in sorted(chapters, key=lambda c: c['id']):
		hyphenated_id = hyphenate_id(chapter["id"], ch='/')
		fancy_title = f'{hyphenated_id} — {chapter["title"]}'

		epub_chapter = epub.EpubHtml(title=fancy_title, file_name=f'{chapter["id"]}.xhtml', lang='en-US')
		epub_chapter.add_link(href='style/stylesheet.css', rel='stylesheet', type='text/css')

		epub_chapter.content = create_chapter_content(chapter)

		book.add_item(epub_chapter)
		epub_chapters.append(epub_chapter)

	# define Table Of Contents
	book.toc = epub_chapters

	# add default NCX and Nav file
	book.add_item(epub.EpubNcx())
	book.add_item(epub.EpubNav())

	# add CSS file
	book.add_item(nav_css)

	# basic spine
	book.spine = ['nav', *epub_chapters]

	# write to the file
	filename = f'{title_to_filename(story_meta["title"])}.epub'
	print('saving epub to', filename)
	epub.write_epub(filename, book, {})


def make_title_page(story_meta):
	pass


def load_story(story_dir):
	available_choices = [{'id': '1', 'type': 'chapter'}]
	chapters = []

	while True:
		try:
			choice = available_choices.pop()
		except IndexError:
			# finished loading
			break

		print('loading', choice['id'])

		if choice['type'] == 'blank':
			continue

		choice_id = choice['id']
		chapter_filename = hashlib.sha256(choice["id"].encode()).hexdigest()
		with open(story_dir / 'chapter' / f'{chapter_filename}.json', 'r', encoding='utf-8') as infile:
			chapter = json.load(infile)
			chapter['content'] = markdown2.markdown(chapter['content'], extras=['smarty-pants'])
			chapters.append(chapter)

		for new_choice in chapter['choices']:
			available_choices.append(new_choice)

	return chapters


def title_to_filename(title: str):
	return "".join([c if c.isalpha() or c.isdigit() or c==' ' else '_' for c in title]).strip()


def args():
    parser = argparse.ArgumentParser(description='Convert a downloaded story into an ePub')
    parser.add_argument('story_dirs', metavar='DIR', type=str, nargs='+',
                        help='the folder containing the downloaded story')

    parsed = parser.parse_args()

    return parsed


def main():
	parsed = args()

	for story_dir in parsed.story_dirs:
		story_dir = pathlib.Path(story_dir)

		print('loading', story_dir)

		for file in story_dir.glob('*'):
			if file.name.endswith('.sqlite') or file.name.startswith('0-') or file.name.endswith('.epub'):
				continue
			# print(file)

		with open(story_dir / 'meta.json', 'r', encoding='utf-8') as infile:
			story_meta = json.load(infile)

		print('processing', story_meta['title'])

		chapters = load_story(story_dir)

		# print(chapters)

		generate_book(story_meta, chapters)


if __name__ == '__main__':
	main()
