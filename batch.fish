#!/usr/local/bin/fish

source ./venv/bin/activate.fish

for url in (cat ./urls.txt);
	python3 scraper/scraper/scrape.py $url
end