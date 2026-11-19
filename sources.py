"""Where winning numbers and invoice details come from.

Sources, tried in order:
  1. MoF e-invoice API (QryWinningList)  - needs MOF_APP_ID (apply at
     https://www.einvoice.nat.gov.tw/ -> 開發者專區 / API 申請).
  2. MoF public RSS feed https://invoice.etax.nat.gov.tw/invoice.xml - no key.
  3. Local file winning_numbers.json      - offline fallback / manual entry.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from invoice import Invoice, WinningNumbers

MOF_API = "https://api.einvoice.nat.gov.tw/PB2CAPIVAN/invapp/InvApp"
RSS_URL = "https://invoice.etax.nat.gov.tw/invoice.xml"
LOCAL_FILE = Path(__file__).with_name("winning_numbers.json")
CACHE_TTL = 6 * 3600
UA = "receipt-checker/0.1"

_cache: dict[str, tuple[float, WinningNumbers]] = {}


def _http(url: str, data: dict | None = None, timeout: int = 15) -> str:
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ---- 1. MoF API ------------------------------------------------------------

def from_mof_api(term: str, app_id: str) -> WinningNumbers:
    raw = _http(MOF_API, {"version": "0.2", "action": "QryWinningList",
                          "invTerm": term, "UUID": str(uuid.uuid4()),
                          "appID": app_id})
    d = json.loads(raw)
    if str(d.get("code")) != "200":
        raise RuntimeError(f"MoF API error {d.get('code')}: {d.get('msg')}")
    return parse_mof_winning(term, d)


def parse_mof_winning(term: str, d: dict) -> WinningNumbers:
    def nums(prefix, n):
        return [d[f"{prefix}{i}"] for i in range(1, n + 1)
                if d.get(f"{prefix}{i}")]
    return WinningNumbers(term=term, special=d["superPrizeNo"],
                          grand=d["spcPrizeNo"],
                          first=nums("firstPrizeNo", 10),
                          additional_sixth=nums("sixthPrizeNo", 6),
                          source="MoF e-invoice API")


def query_invoice_detail(inv: Invoice, app_id: str) -> dict:
    """Ask the MoF platform whether this invoice exists and what it contains.

    Uses qryInvDetail with the data from the left QR code. Requires an App ID.
    """
    if not (inv.random_code and inv.encrypt and inv.seller_id):
        raise ValueError("Detail lookup needs a scanned LEFT QR code")
    raw = _http(MOF_API, {
        "version": "0.5", "type": "QRCode", "invNum": inv.number,
        "action": "qryInvDetail", "generation": "V2", "invTerm": inv.term,
        "invDate": inv.date.strftime("%Y/%m/%d"), "encrypt": inv.encrypt,
        "sellerID": inv.seller_id, "UUID": str(uuid.uuid4()),
        "randomNumber": inv.random_code, "appID": app_id,
    })
    return json.loads(raw)


# ---- 2. Public RSS -----------------------------------------------------------

def parse_rss(xml: str) -> list[WinningNumbers]:
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        title = re.search(r"<title>(.*?)</title>", item, re.S)
        desc = re.search(r"<description>(.*?)</description>", item, re.S)
        if not (title and desc):
            continue
        t = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", title.group(1)))
        m = re.search(r"(\d{2,3})\s*年\D*\d{1,2}\D+(\d{1,2})\s*月", t)
        if not m:
            continue
        term = f"{int(m.group(1)):03d}{int(m.group(2)):02d}"
        body = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", desc.group(1)))
        body = re.sub(r"<[^>]+>", "\n", body)

        def grab(label):
            mm = re.search(label + r"\s*[：:]\s*([\d、,，\s]+)", body)
            return re.findall(r"\d{3,8}", mm.group(1)) if mm else []
        special, grand, first = grab("特別獎"), grab("特獎"), grab("頭獎")
        if special and grand and first:
            out.append(WinningNumbers(term, special[0], grand[0], first,
                                      grab("增開六獎"), source="MoF public RSS"))
    return out


def from_rss(term: str) -> WinningNumbers:
    for wn in parse_rss(_http(RSS_URL)):
        if wn.term == term:
            return wn
    raise LookupError(f"Term {term} not in the public feed (not drawn yet?)")


# ---- 3. Local file -----------------------------------------------------------

def from_local(term: str) -> WinningNumbers:
    if LOCAL_FILE.exists():
        for d in json.loads(LOCAL_FILE.read_text("utf-8")):
            if d["term"] == term:
                return WinningNumbers.from_dict({**d, "source": "local file"})
    raise LookupError(f"Term {term} not in {LOCAL_FILE.name}")


def get_winning_numbers(term: str) -> WinningNumbers:
    hit = _cache.get(term)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    errors = []
    app_id = os.environ.get("MOF_APP_ID")
    attempts = ([lambda: from_mof_api(term, app_id)] if app_id else []) + \
               [lambda: from_rss(term), lambda: from_local(term)]
    for fn in attempts:
        try:
            wn = fn()
            _cache[term] = (time.time(), wn)
            return wn
        except Exception as e:  # try the next source
            errors.append(str(e))
    raise LookupError("No winning numbers for term %s: %s" % (term, " | ".join(errors)))
