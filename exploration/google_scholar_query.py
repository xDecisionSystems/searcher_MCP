#!/usr/bin/env python3
import json

from scholarly import scholarly

# Edit these variables directly for quick local exploration.
QUERY = "aviation noise model"
LIMIT = 5
MIN_YEAR = 2010
MAX_YEAR = 2020

if LIMIT < 1:
    raise SystemExit("LIMIT must be >= 1")

if MIN_YEAR is not None and MAX_YEAR is not None and MIN_YEAR > MAX_YEAR:
    raise SystemExit("MIN_YEAR cannot be greater than MAX_YEAR")

results = []
search_iter = scholarly.search_pubs(QUERY)

for _ in range(LIMIT):
    try:
        item = next(search_iter)
    except StopIteration:
        break

    bib = item.get("bib", {})
    author_field = bib.get("author", "")
    if isinstance(author_field, str):
        authors = [part.strip() for part in author_field.split(" and ") if part.strip()]
    elif isinstance(author_field, list):
        authors = [str(part).strip() for part in author_field if str(part).strip()]
    else:
        authors = []

    year_raw = bib.get("pub_year", "")
    try:
        year_int = int(str(year_raw).strip())
    except (TypeError, ValueError):
        year_int = None

    if MIN_YEAR is not None and year_int is not None and year_int < MIN_YEAR:
        continue
    if MAX_YEAR is not None and year_int is not None and year_int > MAX_YEAR:
        continue

    results.append(
        {
            "title": bib.get("title", ""),
            "authors": authors,
            "year": year_raw,
            "venue": bib.get("venue", ""),
            "url": item.get("pub_url", "") or item.get("eprint_url", ""),
        }
    )

payload = {
    "query": QUERY,
    "limit": LIMIT,
    "min_year": MIN_YEAR,
    "max_year": MAX_YEAR,
    "results": results,
}
print(json.dumps(payload, indent=2))
