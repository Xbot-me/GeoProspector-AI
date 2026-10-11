"""
Contact enrichment sources used by nodes/contact_finder.py.

Each module returns plain dicts and never raises on network trouble: a
missing source just contributes nothing.

  website.py         crawl the business site: emails, phones, social and
                     LinkedIn links, schema.org people, page text
  ai_extract.py      Gemini pulls owner/staff names + roles from page text
                     (names are kept only if they literally appear in it)
  hunter.py          Hunter.io domain search: named people, roles, emails,
                     phones, LinkedIn (needs HUNTER_API_KEY)
  companies_house.py UK company officers (needs COMPANIES_HOUSE_API_KEY)
  web_search.py      DuckDuckGo: Facebook/Instagram, LinkedIn person and
                     company pages (URLs only, LinkedIn is never scraped)
"""
