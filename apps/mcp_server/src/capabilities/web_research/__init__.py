"""Web research: search the web and read a page through Tavily."""

from src.services import capability_meta

META = capability_meta.register(folder="web_research", id="web", label="Web Research")
