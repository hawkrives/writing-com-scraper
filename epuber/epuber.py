import argparse
import pathlib
import json
from ebooklib import epub
import markdown2


def generate_chapter_links(choices):
	if not choices:
		return ''

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


def generate_chapter_header(chapter):
	last_id = chapter["id"][:-1]
	yield '<hr/>'
	if last_id:
		yield f'<a href="{last_id}.xhtml">Go Back</a>'
		yield f' | '
	yield f'<a href="nav.xhtml">Overview</a>'
	yield f'<h1>{chapter["title"]}</h1>'
	yield f'<p>by {chapter["author"]} on {chapter["date"]}</p>'


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
		hyphenated_id = '-'.join([*chapter["id"]])
		fancy_title = f'[{hyphenated_id}] {chapter["title"]}'

		epub_chapter = epub.EpubHtml(title=fancy_title, file_name=f'{chapter["id"]}.xhtml', lang='en-US')
		epub_chapter.add_link(href='style/stylesheet.css', rel='stylesheet', type='text/css')

		choice_links = ''.join(list(generate_chapter_links(chapter['choices'])))
		header = ''.join(list(generate_chapter_header(chapter)))
		epub_chapter.content = header + chapter['content'] + choice_links

		book.add_item(epub_chapter)
		epub_chapters.append(epub_chapter)

	# define Table Of Contents
	book.toc = (
		epub_chapters
	)

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
		with open(story_dir / f'{choice_id}.json', 'r', encoding='utf-8') as infile:
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
    parser.add_argument('story_dir', type=str,
                        help='the folder containing the downloaded story')

    parsed = parser.parse_args()

    parsed.story_dir = pathlib.Path(parsed.story_dir)

    return parsed


def main():
	parsed = args()

	story_dir = parsed.story_dir

	for file in story_dir.glob('*'):
		if file.name.endswith('.sqlite') or file.name.startswith('0-') or file.name.endswith('.epub'):
			continue
		# print(file)

	with open(story_dir / 'meta.json', 'r', encoding='utf-8') as infile:
		story_meta = json.load(infile)

	chapters = load_story(story_dir)

	# print(chapters)

	generate_book(story_meta, chapters)


if __name__ == '__main__':
	main()
