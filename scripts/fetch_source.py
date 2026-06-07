"""Fetch breed source data from the AKC website.

Usage:
    python scripts/fetch_source.py "Border Collie"
    python scripts/fetch_source.py "Border Collie" --json   # print raw JSON

Returns a dict of breed facts scraped from https://www.akc.org/dog-breeds/<slug>/.
The AKC page embeds structured breed data in a JSON island and in trait tables;
we parse both and fall back gracefully so a partial scrape still yields useful
source material for the writer. This module is imported by generate_blog.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None

# Allow running as a script (python scripts/fetch_source.py) or as a module.
try:
    from _common import slugify
except ImportError:  # pragma: no cover
    from scripts._common import slugify

AKC_BASE = "https://www.akc.org/dog-breeds"
# A real browser UA — AKC returns 403 to the default requests UA.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 20


def _akc_url(breed: str) -> str:
    return f"{AKC_BASE}/{slugify(breed)}/"


def _extract_traits(soup: "BeautifulSoup") -> dict[str, str]:
    """Pull the breed-trait rows (size, lifespan, temperament, group, etc.)."""
    traits: dict[str, str] = {}

    # AKC renders trait pairs in elements tagged with breed-trait classes; the
    # exact markup shifts over time, so we match loosely on attribute fragments.
    for row in soup.find_all(attrs={"class": lambda c: bool(c) and "attribute-list" in " ".join(c if isinstance(c, list) else [c])}):
        label_el = row.find(attrs={"class": lambda c: bool(c) and "title" in " ".join(c if isinstance(c, list) else [c])})
        value_el = row.find(attrs={"class": lambda c: bool(c) and "value" in " ".join(c if isinstance(c, list) else [c])})
        if label_el and value_el:
            label = label_el.get_text(" ", strip=True)
            value = value_el.get_text(" ", strip=True)
            if label and value:
                traits[label] = value
    return traits


def _extract_description(soup: "BeautifulSoup") -> str:
    """Grab the meta description / intro paragraph as a prose summary."""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return meta["content"].strip()
    p = soup.find("p")
    return p.get_text(" ", strip=True) if p else ""


def _extract_jsonld(soup: "BeautifulSoup") -> dict[str, Any]:
    """Some AKC data lives in a ld+json island; return it if present."""
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def fetch_breed_source(breed: str) -> dict[str, Any]:
    """Fetch and parse AKC source data for a breed.

    Always returns a dict with at least 'breed' and 'source_url'. Network or
    parse failures populate 'error' / 'warning' rather than raising, so the
    caller can decide whether the partial data is enough to proceed.
    """
    url = _akc_url(breed)
    result: dict[str, Any] = {"breed": breed, "source_url": url}

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        result["error"] = f"Failed to fetch {url}: {exc}"
        return result

    if BeautifulSoup is None:
        result["warning"] = (
            "beautifulsoup4 not installed; returning raw HTML length only."
        )
        result["raw_html_length"] = len(resp.text)
        return result

    soup = BeautifulSoup(resp.text, "html.parser")
    result["title"] = (soup.title.get_text(strip=True) if soup.title else breed)
    result["description"] = _extract_description(soup)
    result["traits"] = _extract_traits(soup)

    jsonld = _extract_jsonld(soup)
    if jsonld:
        result["jsonld"] = jsonld

    if not result["traits"] and not result["description"]:
        result["warning"] = (
            "Fetched the page but could not parse breed facts — AKC markup may "
            "have changed. The writer will rely on the breed name + any prose."
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch AKC breed source data.")
    parser.add_argument("breed", help='Breed name, e.g. "Border Collie"')
    parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    args = parser.parse_args()

    data = fetch_breed_source(args.breed)

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0 if "error" not in data else 1

    print(f"Breed:  {data['breed']}")
    print(f"Source: {data['source_url']}")
    if "error" in data:
        print(f"ERROR:  {data['error']}", file=sys.stderr)
        return 1
    if "warning" in data:
        print(f"WARN:   {data['warning']}", file=sys.stderr)
    if data.get("description"):
        print(f"\n{data['description']}\n")
    for label, value in (data.get("traits") or {}).items():
        print(f"  - {label}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
