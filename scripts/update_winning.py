"""Refresh static/winning.json from the Ministry of Finance public feed.

    python3 scripts/update_winning.py

Run daily by .github/workflows/update-winning.yml. Terms already in the file
that have dropped out of the feed are kept (up to KEEP terms), so receipts
stay checkable for their whole claim window. The file is only rewritten when
the numbers change, so the Action commits nothing on quiet days.
Exits with status 1 if the feed can't be fetched or parsed (file untouched).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sources  # noqa: E402

OUT = ROOT / "static" / "winning.json"
KEEP = 6  # two-month terms: one year of draws


def merge(existing: list[dict], fresh: list[dict], keep: int = KEEP) -> list[dict]:
    by_term = {d["term"]: d for d in existing}
    by_term.update({d["term"]: d for d in fresh})
    return [by_term[t] for t in sorted(by_term, reverse=True)[:keep]]


def main() -> int:
    try:
        fresh = [wn.__dict__ for wn in sources.parse_rss(sources._http(sources.RSS_URL, timeout=30))]
    except Exception as e:
        print(f"Could not fetch {sources.RSS_URL}: {e}", file=sys.stderr)
        return 1
    if not fresh:
        print("Feed fetched but no winning numbers could be parsed", file=sys.stderr)
        return 1
    old = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {"terms": []}
    terms = merge(old.get("terms", []), fresh)
    if terms == old.get("terms"):
        print(f"No change ({len(terms)} terms, newest {terms[0]['term']})")
        return 0
    OUT.write_text(json.dumps({
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": sources.RSS_URL,
        "terms": terms,
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"Updated {OUT.relative_to(ROOT)}: " + ", ".join(t["term"] for t in terms))
    return 0


if __name__ == "__main__":
    sys.exit(main())
