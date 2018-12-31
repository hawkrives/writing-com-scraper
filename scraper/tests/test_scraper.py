from scraper.scrape import get_id


def test_get_id():
	assert get_id('/main/interact/item_id/1234567-PLEASE-ADD/') == 1234567
	assert get_id('/main/interact/item_id/7654321-Title-------PLEASE-ADD/') == 7654321
