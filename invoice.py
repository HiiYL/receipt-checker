"""Taiwan uniform invoice (統一發票) parsing and prize checking.

No third-party dependencies. All dates use the ROC (Minguo) calendar where
the government formats do: ROC year = Gregorian year - 1911.
"""
from __future__ import annotations

import base64
import datetime as dt
import re
from dataclasses import dataclass, field, asdict

INVOICE_NO_RE = re.compile(r"^[A-Z]{2}\d{8}$")


@dataclass
class Item:
    name: str
    quantity: str
    unit_price: str


@dataclass
class Invoice:
    number: str                 # e.g. "AB12345678"
    date: dt.date               # Gregorian date
    random_code: str = ""       # 4 digits, needed for detail lookup
    sales_amount: int | None = None   # untaxed
    total_amount: int | None = None   # tax included
    buyer_id: str = ""          # "00000000" when no tax ID was given
    seller_id: str = ""
    encrypt: str = ""           # 24-char verification field from the QR
    items: list[Item] = field(default_factory=list)

    @property
    def digits(self) -> str:
        return self.number[-8:]

    @property
    def term(self) -> str:
        return term_for(self.date)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        d["term"] = self.term
        return d


# --------------------------------------------------------------------------
# Periods (期別). Invoices are grouped into two-month periods; the term code
# is the ROC year plus the even month, e.g. Sep-Oct 2025 -> "11410".
# --------------------------------------------------------------------------

def term_for(d: dt.date) -> str:
    month = d.month if d.month % 2 == 0 else d.month + 1
    return f"{d.year - 1911:03d}{month:02d}"


def term_label(term: str) -> str:
    y, m = int(term[:3]), int(term[3:])
    return f"{y}年{m - 1:02d}-{m:02d}月"


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + n
    return idx // 12, idx % 12 + 1


def term_schedule(term: str) -> dict:
    """Draw date and claim window for a term (rules in force since 2011)."""
    year, month = int(term[:3]) + 1911, int(term[3:])
    dy, dm = _add_months(year, month, 1)
    draw = dt.date(dy, dm, 25)
    sy, sm = _add_months(year, month, 2)
    ey, em = _add_months(year, month, 5)
    return {
        "draw_date": draw.isoformat(),
        "claim_start": dt.date(sy, sm, 6).isoformat(),
        "claim_end": dt.date(ey, em, 5).isoformat(),
    }


def latest_drawn_terms(today: dt.date | None = None, count: int = 2) -> list[str]:
    """Terms whose numbers have been drawn and that may still be claimable."""
    today = today or dt.date.today()
    terms = []
    y, m = today.year, today.month if today.month % 2 == 0 else today.month + 1
    for _ in range(count + 2):
        t = f"{y - 1911:03d}{m:02d}"
        if dt.date.fromisoformat(term_schedule(t)["draw_date"]) <= today:
            terms.append(t)
        y, m = _add_months(y, m, -2)
    return terms[:count]


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def _roc_date(s: str) -> dt.date:
    return dt.date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))


def parse_left_qr(text: str) -> Invoice:
    """Parse the left QR code printed on an e-invoice proof (電子發票證明聯).

    Layout of the fixed 77-char header (MoF spec):
      0-9   invoice number    10-16 ROC date yyyMMdd   17-20 random code
      21-28 sales amount hex  29-36 total amount hex   37-44 buyer ID
      45-52 seller ID         53-76 encryption field
    followed by ':'-separated fields: custom area, items on this code,
    total items, encoding (0=Big5, 1=UTF-8, 2=Base64), then name:qty:price...
    """
    text = text.strip()
    if len(text) < 77 or not INVOICE_NO_RE.match(text[:10]):
        raise ValueError("Not a Taiwan e-invoice left QR code")
    inv = Invoice(
        number=text[:10],
        date=_roc_date(text[10:17]),
        random_code=text[17:21],
        sales_amount=int(text[21:29], 16),
        total_amount=int(text[29:37], 16),
        buyer_id=text[37:45],
        seller_id=text[45:53],
        encrypt=text[53:77],
    )
    rest = text[77:]
    if rest.startswith(":"):
        fields = rest[1:].split(":")
        encoding = fields[3] if len(fields) > 3 else "1"
        inv.items = _parse_items(fields[4:], encoding)
    return inv


def parse_right_qr(text: str, encoding: str = "1") -> list[Item]:
    """The right QR starts with '**' and continues the item list."""
    text = text.strip()
    if not text.startswith("**"):
        raise ValueError("Not a right-hand e-invoice QR code")
    return _parse_items(text[2:].split(":"), encoding)


def _parse_items(fields: list[str], encoding: str) -> list[Item]:
    items = []
    for i in range(0, len(fields) - 2, 3):
        name = fields[i]
        if encoding == "2":
            try:
                name = base64.b64decode(name).decode("utf-8", "replace")
            except Exception:
                pass
        if name:
            items.append(Item(name, fields[i + 1], fields[i + 2]))
    return items


def parse_barcode(text: str) -> Invoice:
    """1D barcode on e-invoice proofs: yyyMM(5) + invoice no(10) + random(4).

    The barcode carries the period's second month, not the exact day, so the
    date is set to the 1st of that month (sufficient for prize checking).
    """
    text = text.strip()
    m = re.fullmatch(r"(\d{3})(\d{2})([A-Z]{2}\d{8})(\d{4})", text)
    if not m:
        raise ValueError("Not a Taiwan e-invoice barcode")
    return Invoice(number=m.group(3),
                   date=dt.date(int(m.group(1)) + 1911, int(m.group(2)), 1),
                   random_code=m.group(4))


def parse_any(text: str) -> Invoice:
    for fn in (parse_left_qr, parse_barcode):
        try:
            return fn(text)
        except ValueError:
            continue
    raise ValueError("Unrecognised code. Scan the LEFT QR code or the barcode.")


def manual_invoice(number: str, date: str) -> Invoice:
    """Typed in from a paper (traditional) invoice. date is YYYY-MM-DD."""
    number = number.strip().upper().replace("-", "").replace(" ", "")
    if re.fullmatch(r"\d{8}", number):
        number = "XX" + number          # letters don't affect prizes
    if not INVOICE_NO_RE.match(number):
        raise ValueError("Invoice number must be 2 letters + 8 digits")
    return Invoice(number=number, date=dt.date.fromisoformat(date))


# --------------------------------------------------------------------------
# Prize checking
# --------------------------------------------------------------------------

FIRST_PRIZE_TIERS = [  # (matching trailing digits, name, NT$)
    (8, "頭獎 First prize", 200_000),
    (7, "二獎 Second prize", 40_000),
    (6, "三獎 Third prize", 10_000),
    (5, "四獎 Fourth prize", 4_000),
    (4, "五獎 Fifth prize", 1_000),
    (3, "六獎 Sixth prize", 200),
]


@dataclass
class WinningNumbers:
    term: str
    special: str                 # 特別獎 NT$10,000,000
    grand: str                   # 特獎 NT$2,000,000
    first: list[str]             # 頭獎 (usually 3)
    additional_sixth: list[str] = field(default_factory=list)  # 增開六獎 (3 digits)
    source: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "WinningNumbers":
        return cls(term=d["term"], special=d["special"], grand=d["grand"],
                   first=list(d["first"]),
                   additional_sixth=list(d.get("additional_sixth", [])),
                   source=d.get("source", ""))


def check(inv: Invoice, wn: WinningNumbers) -> dict:
    if inv.term != wn.term:
        raise ValueError(f"Invoice is for term {inv.term}, numbers are for {wn.term}")
    n = inv.digits
    result = {"won": False, "prize": None, "amount": 0, "matched": None}

    def win(prize, amount, matched):
        result.update(won=True, prize=prize, amount=amount, matched=matched)
        return result

    if n == wn.special:
        return win("特別獎 Special prize", 10_000_000, wn.special)
    if n == wn.grand:
        return win("特獎 Grand prize", 2_000_000, wn.grand)
    best = None
    for f in wn.first:
        for k, name, amt in FIRST_PRIZE_TIERS:
            if n[-k:] == f[-k:]:
                if best is None or amt > best[1]:
                    best = (name, amt, f)
                break
    if best:
        return win(*best)
    for s in wn.additional_sixth:
        if n[-3:] == s[-3:]:
            return win("增開六獎 Additional sixth prize", 200, s)
    return result

