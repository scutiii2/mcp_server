"""Web scraping: scrape a page, map a site and crawl it through Firecrawl."""

from src.services import capability_meta

META = capability_meta.register(folder="firecrawl", id="scrape", label="Web Scraping")
