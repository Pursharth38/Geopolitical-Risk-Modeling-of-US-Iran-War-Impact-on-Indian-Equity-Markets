"""
Milestone 1 — Track 2A, Step 1: scrape the raw war-events timeline.

Downloads Wikipedia's "Timeline of the 2026 Iran war" and extracts EVERY dated
entry into a raw CSV. This is deliberately a high-recall dump: the page logs
almost every day of the conflict, most of which does not move markets. Deciding
which entries are market-relevant, scoring severity, and de-duplicating is a
separate judgment step (Track 2A, Step 2) done later — this script does no such
filtering, so the raw source stays faithful and auditable.

Page structure (verified 2026-07 against the live page):
  * <h2> = a date header, e.g. "28 February" (year is always 2026 on this page).
    Non-date <h2> (References, See also, ...) reset the current date to None.
  * <h3> = a sub-theme within a day, e.g. "Iranian strikes", "Other developments".
  * Event text lives in BOTH <p> paragraphs (used on heavy-combat early days,
    nested in sub-sections) AND <li> bullets (used on sparser later days).
    Both are captured, tagged with entry_type.

Output: data_raw/war_events/wiki_timeline_raw.csv with one row per entry:
    raw_id, source, event_date, date_header, section, entry_type, text, source_url, scraped_at

Usage:
    py src/etl/scrape_war_events.py
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scrape_war_events")

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}

# Parent containers whose text is navigation/citations, not timeline content.
SKIP_PARENT_CLASSES = ("reflist", "navbox", "reference", "mw-editsection", "thumbcaption")

MAX_RETRIES = 3
RETRY_SLEEP_SECONDS = 3.0


def fetch_html(url: str) -> str:
    """GET a page with a polite UA and a small retry loop."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": config.SCRAPER_USER_AGENT},
                timeout=30,
            )
            resp.raise_for_status()
            log.info("Fetched %s (%d bytes)", url, len(resp.text))
            return resp.text
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("  attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            time.sleep(RETRY_SLEEP_SECONDS)
    assert last_exc is not None
    raise last_exc


def _parse_date_header(header: str, year: int) -> str | None:
    """Turn a header like '28 February' into ISO '2026-02-28'. None if not a date."""
    parts = header.replace("\xa0", " ").split()
    day = month = None
    for p in parts:
        token = p.strip(",")
        if token.isdigit() and 1 <= int(token) <= 31:
            day = int(token)
        elif token in MONTHS:
            month = MONTHS[token]
    if day and month:
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    return None


def _is_skippable(el) -> bool:
    """True if the element sits inside a navigation/citation container."""
    for cls in SKIP_PARENT_CLASSES:
        if el.find_parent(class_=cls) is not None:
            return True
    # Skip anything inside a table (infoboxes, casualty tables) — not timeline prose.
    if el.find_parent("table") is not None:
        return True
    return False


def _clean_text(el) -> str:
    """Extract entry text, dropping inline citation superscripts like [1][2]."""
    clone = BeautifulSoup(str(el), "lxml")
    for sup in clone.select("sup.reference"):
        sup.decompose()
    for edit in clone.select("span.mw-editsection"):
        edit.decompose()
    return clone.get_text(" ", strip=True)


def parse_timeline(html: str, url: str, year: int) -> list[dict]:
    """Walk the page in document order, emitting one row per dated entry."""
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("div.mw-body-content") or soup

    rows: list[dict] = []
    cur_date: str | None = None
    cur_header: str | None = None
    cur_anchor: str = url
    cur_section: str | None = None
    scraped_at = datetime.now().isoformat(timespec="seconds")

    for el in body.descendants:
        name = getattr(el, "name", None)
        if name == "h2":
            header = el.get_text(" ", strip=True)
            iso = _parse_date_header(header, year)
            cur_date = iso
            cur_header = header if iso else None
            cur_section = None
            anchor_id = el.get("id") or ""
            cur_anchor = f"{url}#{anchor_id}" if (iso and anchor_id) else url
        elif name == "h3" and cur_date:
            cur_section = el.get_text(" ", strip=True)
        elif name in ("p", "li") and cur_date:
            if name == "li" and el.find_parent("li") is not None:
                continue  # nested list item — captured via its parent
            if _is_skippable(el):
                continue
            text = _clean_text(el)
            if not text or len(text) < 3:
                continue
            rows.append({
                "source": "wikipedia_timeline",
                "event_date": cur_date,
                "date_header": cur_header,
                "section": cur_section,
                "entry_type": name,
                "text": text,
                "source_url": cur_anchor,
                "scraped_at": scraped_at,
            })
    # Stable, traceable ids in document order.
    for i, r in enumerate(rows, start=1):
        r["raw_id"] = f"wt_{i:04d}"
    return rows


def main() -> int:
    config.DIRS["war_events"].mkdir(parents=True, exist_ok=True)

    html = fetch_html(config.WIKI_TIMELINE_URL)
    rows = parse_timeline(html, config.WIKI_TIMELINE_URL, config.WAR_EVENTS_YEAR)

    if not rows:
        log.error("No entries parsed — page structure may have changed.")
        return 1

    cols = ["raw_id", "source", "event_date", "date_header", "section",
            "entry_type", "text", "source_url", "scraped_at"]
    df = pd.DataFrame(rows)[cols].sort_values(["event_date", "raw_id"]).reset_index(drop=True)
    df.to_csv(config.WIKI_TIMELINE_RAW_CSV, index=False)

    log.info("Wrote %d raw entries -> %s",
             len(df), config.WIKI_TIMELINE_RAW_CSV.relative_to(config.PROJECT_ROOT))
    log.info("Date span: %s -> %s across %d distinct dates",
             df["event_date"].min(), df["event_date"].max(), df["event_date"].nunique())
    log.info("Entry types: %s", df["entry_type"].value_counts().to_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main())
