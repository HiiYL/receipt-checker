# 發票對獎 Receipt Checker

Scan a Taiwan e-invoice (or type a paper invoice) and check it against the
Ministry of Finance (財政部) uniform-invoice winning numbers.

![screenshot](screenshot.png)

## Use it

Live at **https://hiiyl.github.io/receipt-checker/** (GitHub Pages, HTTPS, so the
live camera works on phones). Everything runs in the browser: receipts never leave
your device.

## How it works

- `static/` is the whole website. `static/invoice.js` reads the QR code, barcode or
  typed-in number, works out the period and checks every prize tier.
- `static/winning.json` holds the winning numbers. The **Update winning numbers**
  Action runs `scripts/update_winning.py` every day at 22:00 Taiwan time, fetches the
  Ministry of Finance public feed, and commits the file only when the numbers change.
  The last 6 periods are kept, so receipts stay checkable for their whole claim window.
- The **Deploy to GitHub Pages** Action runs the tests and publishes `static/` on every
  push to `main` and after each update run.

To refresh the numbers by hand: Actions → Update winning numbers → Run workflow, or
locally `python3 scripts/update_winning.py` and commit `static/winning.json`.

## Run it locally

```bash
cd receipt-checker
python3 -m http.server -d static 8000     # open http://localhost:8000
```

`python3 server.py` also still works. It serves the same page plus the JSON API below
(and can use the official MoF API, see the end of this file).

## What it does

1. **Read the receipt**
   - *Scan camera / Photo*: decodes the **left QR code** of an e-invoice proof
     (電子發票證明聯): invoice number, date, random code, sales and total amounts,
     buyer and seller tax IDs, and items. The 1D barcode also works.
     Decoding uses [ZXing](https://github.com/Sec-ant/zxing-wasm) (WebAssembly), which
     finds every code in the photo, including rotated, small or slightly blurry ones.
     If nothing usable is found (after 20 seconds of camera scanning, or in a photo),
     the app says why and switches to *Type in*.
   - *Type in*: invoice number and date from a traditional paper invoice.
2. **Work out the period** (期別, two months, e.g. 115年07-08月 = `11508`), its draw
   date (25th of the following odd month) and claim window (6th of the next month,
   for 3 months).
3. **Look up the winning numbers** in `winning.json`, which comes from the MoF public
   feed `https://invoice.etax.nat.gov.tw/invoice.xml` (no key needed). If a period
   was drawn but the daily update hasn't picked it up yet, the receipt is kept as
   pending and re-checked automatically.
4. **Check every prize tier**: 特別獎 NT$10M, 特獎 NT$2M, 頭獎 NT$200k down to
   六獎 NT$200 on the last 3 digits, plus any 增開六獎. It tells you if you won,
   if the period hasn't been drawn yet, or if the claim window has passed.

## Saved receipts

Every checked receipt is saved in the browser (localStorage), so the list and the
total to claim survive a reload. It stays on that device only. Receipts from a period
that hasn't been drawn yet are re-checked automatically the next time you open the
app after the draw date.

## Optional: official MoF API

Only for the local Python server (an App ID is secret, so it can't be used on the
public GitHub Pages site). Apply for an App ID on the e-invoice platform (https://www.einvoice.nat.gov.tw/,
開發者專區 → API 申請), then:

```bash
MOF_APP_ID=your_app_id python3 server.py
```

With an App ID the server uses the API for winning numbers, and a
`POST /api/check` with `"verify": true` also calls `qryInvDetail` to confirm the
invoice exists on the MoF platform. This part follows the published spec but has not
been tested against the live API.

## API

```
POST /api/check  {"code": "<QR or barcode text>"}
POST /api/check  {"number": "AB12345678", "date": "2026-08-14"}
GET  /api/winning?term=11508      (no term: the last two drawn periods)
```

## Tests

```bash
node --test "tests/*.test.js"            # browser logic (static/invoice.js)
python3 -m unittest discover -s tests -v  # Python server and the updater
```

## Files

- `static/index.html`: the phone-friendly web app
- `static/invoice.js`: parsing, periods and prize rules (JavaScript, runs in the browser)
- `static/winning.json`: winning numbers, refreshed daily by GitHub Actions
- `scripts/update_winning.py`: fetches the MoF feed into `winning.json`
- `.github/workflows/`: daily update and Pages deploy
- `invoice.py`: the same logic in Python, for the local server
- `sources.py`: MoF API, public feed, local file, with a 6-hour cache
- `server.py`: optional local web server and JSON API
