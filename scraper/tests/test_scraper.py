from scraper.scrape import get_id, parse_writing_time


def test_get_id():
	assert get_id('/main/interact/item_id/1234567-PLEASE-ADD/') == 1234567
	assert get_id('/main/interact/item_id/7654321-Title-------PLEASE-ADD/') == 7654321


def test_parse_writing_time():
	# Created: October 7th, 2007 at 5:27pm
    # Modified: December 26th, 2018 at 8:16pm
	assert parse_writing_time('Created: October 7th, 2007 at 5:27pm') == '2007-10-07T17:27:00+00:00'
	assert parse_writing_time('Modified: December 26th, 2018 at 8:16pm') == '2018-12-26T20:16:00+00:00'
