#!/usr/bin/env python3
"""Find Cleveland Clinic page/image candidates for all uncached cards in parallel."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36"
DEFAULT_WORKERS = 8
DEFAULT_RESULTS = 3
ALGOLIA_APPLICATION_ID = "NLI34IG0X3"
ALGOLIA_SEARCH_ONLY_API_KEY = "a134144c18c63ca12a4a12bcfb2ad7d7"
ALGOLIA_INDEX = "Sitecore_Prod"
ALGOLIA_ENDPOINT = (
    f"https://{ALGOLIA_APPLICATION_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"
)


def is_cleveland_url(value: str) -> bool:
    host = (urlparse(value).hostname or "").lower().rstrip(".")
    return host == "clevelandclinic.org" or host.endswith(".clevelandclinic.org")


def is_site_chrome_or_placeholder(value: str) -> bool:
    lowered = value.casefold()
    return any(marker in lowered for marker in (
        "/org/social/cc-fb.jpg",
        "/org/logo/",
        "cleveland-clinic-logo",
        "largefeatureimage/aa41aba3-3189-4d99-9f49-b70fe103eef2",
    ))


def fetch(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def clean_text(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())


def search_pages(query: str, limit: int, timeout: float) -> list[dict[str, str]]:
    """Use the same Algolia index as https://my.clevelandclinic.org/search."""
    payload = json.dumps({
        "params": urlencode({"query": query, "hitsPerPage": limit, "getRankingInfo": "true"})
    }).encode("utf-8")
    request = Request(ALGOLIA_ENDPOINT, data=payload, headers={
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "X-Algolia-Application-Id": ALGOLIA_APPLICATION_ID,
        "X-Algolia-API-Key": ALGOLIA_SEARCH_ONLY_API_KEY,
    })
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    pages: list[dict[str, str]] = []
    for hit in result.get("hits", []):
        link = urljoin("https://my.clevelandclinic.org", str(hit.get("url") or "").strip())
        if not is_cleveland_url(link):
            continue
        pages.append({
            "page_url": link,
            "title": clean_text(str(hit.get("title") or hit.get("name") or "")),
            "snippet": clean_text(str(hit.get("meta description") or "")),
        })
        if len(pages) >= limit:
            break
    return pages


class ImageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.images: list[dict[str, str]] = []
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "meta":
            key = (values.get("property") or values.get("name") or "").casefold()
            if key == "og:title" and values.get("content"):
                self.title = values["content"].strip()
            if key in {"og:image", "twitter:image"} and values.get("content"):
                self._add(values["content"], key)
        if tag.casefold() == "img":
            source = values.get("src") or values.get("data-src") or values.get("data-lazy-src")
            if source:
                self._add(source, values.get("alt", ""))

    def _add(self, source: str, label: str) -> None:
        url = urljoin(self.base_url, source.strip())
        if (
            is_cleveland_url(url)
            and not url.lower().endswith(".svg")
            and not is_site_chrome_or_placeholder(url)
        ):
            self.images.append({"image_url": url, "alt": clean_text(label)})


def inspect_page(page: dict[str, str], timeout: float, image_limit: int) -> dict:
    parser = ImageParser(page["page_url"])
    parser.feed(fetch(page["page_url"], timeout).decode("utf-8", errors="replace"))
    seen: set[str] = set()
    images = []
    for image in parser.images:
        if image["image_url"] in seen:
            continue
        seen.add(image["image_url"])
        images.append(image)
        if len(images) >= image_limit:
            break
    return {**page, "page_title": parser.title or page["title"], "images": images}


def process_card(card: dict, limit: int, timeout: float, image_limit: int) -> dict:
    query = str(card.get("image_query") or card["word"]).strip()
    site_query = str(card.get("semantic_identity") or card["word"]).strip()
    started = time.perf_counter()
    try:
        supplied_pages = card.get("candidate_pages") or []
        if supplied_pages:
            pages = [
                {"page_url": str(url), "title": "", "snippet": ""}
                for url in supplied_pages[:limit] if is_cleveland_url(str(url))
            ]
        else:
            pages = search_pages(site_query, limit, timeout)
    except Exception as error:
        return {
            "word": str(card["word"]), "image_query": query, "site_search_query": site_query,
            "status": "search-failed",
            "error": f"{type(error).__name__}: {error}", "pages": [],
            "seconds": round(time.perf_counter() - started, 3),
        }
    inspected_by_index: dict[int, dict] = {}
    page_errors_by_index: dict[int, dict] = {}
    # Site searches are already independent and concurrent. Inspect every returned
    # page concurrently too, preserving result order without reducing coverage.
    with ThreadPoolExecutor(max_workers=min(len(pages) or 1, limit)) as page_pool:
        page_futures = {
            page_pool.submit(inspect_page, page, timeout, image_limit): (index, page)
            for index, page in enumerate(pages)
        }
        for future in as_completed(page_futures):
            index, page = page_futures[future]
            try:
                inspected_by_index[index] = future.result()
            except Exception as error:
                page_errors_by_index[index] = {
                    "page_url": page["page_url"],
                    "error": f"{type(error).__name__}: {error}",
                }
    inspected = [inspected_by_index[index] for index in sorted(inspected_by_index)]
    page_errors = [page_errors_by_index[index] for index in sorted(page_errors_by_index)]
    status = "success" if inspected and not page_errors else "incomplete" if inspected or page_errors else "no-results"
    return {
        "word": str(card["word"]), "image_query": query, "site_search_query": site_query,
        "status": status,
        "pages": inspected, "page_errors": page_errors,
        "seconds": round(time.perf_counter() - started, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--results-per-term", type=int, default=DEFAULT_RESULTS)
    parser.add_argument("--images-per-page", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error("--workers must be between 1 and 16")

    spec = json.loads(args.spec.expanduser().resolve().read_text(encoding="utf-8"))
    cards = [card for card in spec.get("cards", []) if isinstance(card, dict)]
    started = time.perf_counter()
    results: list[dict | None] = [None] * len(cards)
    with ThreadPoolExecutor(max_workers=min(args.workers, len(cards) or 1)) as pool:
        futures = {
            pool.submit(process_card, card, args.results_per_term, args.timeout, args.images_per_page): index
            for index, card in enumerate(cards)
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()

    final = [item for item in results if item is not None]
    payload = {
        "source_policy": "Cleveland Clinic site-search results and images are restricted to clevelandclinic.org",
        "search_provider": "https://my.clevelandclinic.org/search (Sitecore_Prod Algolia index)",
        "automatic_no_image_decisions": False,
        "cards": len(final),
        "success": sum(item["status"] == "success" for item in final),
        "incomplete": sum(item["status"] != "success" for item in final),
        "total_seconds": round(time.perf_counter() - started, 3),
        "results": final,
    }
    args.output.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.expanduser().resolve().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: payload[key] for key in ("cards", "success", "incomplete", "total_seconds")}, indent=2))


if __name__ == "__main__":
    main()
