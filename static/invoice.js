// Taiwan uniform invoice (統一發票) parsing and prize checking, in the browser.
// A JavaScript port of invoice.py. Dates are plain "YYYY-MM-DD" strings so
// there are no time-zone surprises. ROC year = Gregorian year - 1911.

const INVOICE_NO_RE = /^[A-Z]{2}\d{8}$/;
const pad = (n, w = 2) => String(n).padStart(w, "0");
const iso = (y, m, d) => `${pad(y, 4)}-${pad(m)}-${pad(d)}`;

function validIso(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
  if (!m) return false;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
}

export function localToday(now = new Date()) {
  return iso(now.getFullYear(), now.getMonth() + 1, now.getDate());
}

// ---- Periods (期別) ---------------------------------------------------------

export function termFor(date) {
  const y = +date.slice(0, 4), mo = +date.slice(5, 7);
  return pad(y - 1911, 3) + pad(mo % 2 === 0 ? mo : mo + 1);
}

export function termLabel(term) {
  const y = +term.slice(0, 3), m = +term.slice(3);
  return `${y}年${pad(m - 1)}-${pad(m)}月`;
}

function addMonths(year, month, n) {
  const idx = year * 12 + (month - 1) + n;
  return [Math.floor(idx / 12), (idx % 12) + 1];
}

export function termSchedule(term) {
  const year = +term.slice(0, 3) + 1911, month = +term.slice(3);
  const [dy, dm] = addMonths(year, month, 1);
  const [sy, sm] = addMonths(year, month, 2);
  const [ey, em] = addMonths(year, month, 5);
  return { draw_date: iso(dy, dm, 25), claim_start: iso(sy, sm, 6), claim_end: iso(ey, em, 5) };
}

export function latestDrawnTerms(today, count = 2) {
  const out = [];
  let y = +today.slice(0, 4), m = +today.slice(5, 7);
  if (m % 2) m += 1;
  for (let i = 0; i < count + 2; i++) {
    const t = pad(y - 1911, 3) + pad(m);
    if (termSchedule(t).draw_date <= today) out.push(t);
    [y, m] = addMonths(y, m, -2);
  }
  return out.slice(0, count);
}

// ---- Parsing ---------------------------------------------------------------

function makeInvoice(fields) {
  const inv = { random_code: "", sales_amount: null, total_amount: null, buyer_id: "",
                seller_id: "", encrypt: "", items: [], ...fields };
  inv.digits = inv.number.slice(-8);
  inv.term = termFor(inv.date);
  return inv;
}

function rocDate(s) {
  const d = iso(+s.slice(0, 3) + 1911, +s.slice(3, 5), +s.slice(5, 7));
  if (!validIso(d)) throw new Error("Invalid date in code");
  return d;
}

function b64utf8(s) {
  const bin = atob(s);
  return new TextDecoder().decode(Uint8Array.from(bin, c => c.charCodeAt(0)));
}

function parseItems(fields, encoding) {
  const items = [];
  for (let i = 0; i + 2 < fields.length; i += 3) {
    let name = fields[i];
    if (encoding === "2") { try { name = b64utf8(name); } catch (e) {} }
    if (name) items.push({ name, quantity: fields[i + 1], unit_price: fields[i + 2] });
  }
  return items;
}

// Left QR on an e-invoice proof (電子發票證明聯): fixed 77-char header, then
// ':'-separated custom area, item counts, encoding, and name:qty:price items.
export function parseLeftQr(text) {
  text = text.trim();
  if (text.length < 77 || !INVOICE_NO_RE.test(text.slice(0, 10)))
    throw new Error("Not a Taiwan e-invoice left QR code");
  const hex = s => {
    if (!/^[0-9a-fA-F]{8}$/.test(s)) throw new Error("Not a Taiwan e-invoice left QR code");
    return parseInt(s, 16);
  };
  const inv = makeInvoice({
    number: text.slice(0, 10), date: rocDate(text.slice(10, 17)),
    random_code: text.slice(17, 21), sales_amount: hex(text.slice(21, 29)),
    total_amount: hex(text.slice(29, 37)), buyer_id: text.slice(37, 45),
    seller_id: text.slice(45, 53), encrypt: text.slice(53, 77),
  });
  const rest = text.slice(77);
  if (rest.startsWith(":")) {
    const f = rest.slice(1).split(":");
    inv.items = parseItems(f.slice(4), f.length > 3 ? f[3] : "1");
  }
  return inv;
}

// 1D barcode: yyyMM(5) + invoice no(10) + random(4). Only the period's second
// month is known, so the date is the 1st of that month.
export function parseBarcode(text) {
  const m = /^(\d{3})(\d{2})([A-Z]{2}\d{8})(\d{4})$/.exec(text.trim());
  if (!m) throw new Error("Not a Taiwan e-invoice barcode");
  const month = +m[2];
  if (month < 1 || month > 12) throw new Error("Not a Taiwan e-invoice barcode");
  return makeInvoice({ number: m[3], date: iso(+m[1] + 1911, month, 1), random_code: m[4] });
}

export function parseAny(text) {
  for (const fn of [parseLeftQr, parseBarcode]) {
    try { return fn(text); } catch (e) {}
  }
  throw new Error("Unrecognised code. Scan the LEFT QR code or the barcode.");
}

// Typed in from a paper (traditional) invoice. date is YYYY-MM-DD.
export function manualInvoice(number, date) {
  number = String(number || "").trim().toUpperCase().replace(/[-\s]/g, "");
  if (/^\d{8}$/.test(number)) number = "XX" + number;   // letters don't affect prizes
  if (!INVOICE_NO_RE.test(number)) throw new Error("Invoice number must be 2 letters + 8 digits");
  if (!validIso(date)) throw new Error("Please enter the invoice date");
  return makeInvoice({ number, date });
}

// ---- Prize checking --------------------------------------------------------

const FIRST_PRIZE_TIERS = [
  [8, "頭獎 First prize", 200_000], [7, "二獎 Second prize", 40_000],
  [6, "三獎 Third prize", 10_000], [5, "四獎 Fourth prize", 4_000],
  [4, "五獎 Fifth prize", 1_000], [3, "六獎 Sixth prize", 200],
];

export function check(inv, wn) {
  if (inv.term !== wn.term) throw new Error(`Invoice is for term ${inv.term}, numbers are for ${wn.term}`);
  const n = inv.digits;
  const win = (prize, amount, matched) => ({ won: true, prize, amount, matched });
  if (n === wn.special) return win("特別獎 Special prize", 10_000_000, wn.special);
  if (n === wn.grand) return win("特獎 Grand prize", 2_000_000, wn.grand);
  let best = null;
  for (const f of wn.first) {
    for (const [k, name, amt] of FIRST_PRIZE_TIERS) {
      if (n.slice(-k) === f.slice(-k)) {
        if (!best || amt > best[1]) best = [name, amt, f];
        break;
      }
    }
  }
  if (best) return win(...best);
  for (const s of wn.additional_sixth || [])
    if (n.slice(-3) === s.slice(-3)) return win("增開六獎 Additional sixth prize", 200, s);
  return { won: false, prize: null, amount: 0, matched: null };
}

// Same result shape as server.py's check_payload. `winning` is the list from
// winning.json; `today` is "YYYY-MM-DD".
export function checkPayload(payload, winning, today) {
  const inv = payload.code ? parseAny(payload.code) : manualInvoice(payload.number, payload.date);
  const schedule = termSchedule(inv.term);
  const out = { invoice: inv, term_label: termLabel(inv.term), schedule };

  if (schedule.draw_date > today) {
    return { ...out, status: "not_drawn",
             message: `Numbers for this period are drawn on ${schedule.draw_date}.` };
  }
  const wn = (winning || []).find(w => w.term === inv.term);
  if (!wn) {
    // Drawn, but not in winning.json yet (it is refreshed daily), or too old.
    if (today <= schedule.claim_end) {
      return { ...out, status: "not_drawn",
               message: `Drawn on ${schedule.draw_date}, but the numbers aren't loaded yet. ` +
                        "It will be re-checked automatically next time you open this page." };
    }
    return { ...out, status: "error",
             message: `No winning numbers for ${termLabel(inv.term)}, and its claim period ended ${schedule.claim_end}.` };
  }
  const result = check(inv, wn);
  Object.assign(out, { result, winning_numbers: wn });
  if (!result.won) return { ...out, status: "no_win", message: "Not a winner this time." };
  if (today > schedule.claim_end) {
    return { ...out, status: "expired",
             message: `Won ${result.prize}, but the claim period ended ${schedule.claim_end}.` };
  }
  return { ...out, status: "won",
           message: `Winner! ${result.prize} NT$${result.amount.toLocaleString("en-US")}. ` +
                    `Claim ${schedule.claim_start} to ${schedule.claim_end}.` };
}
