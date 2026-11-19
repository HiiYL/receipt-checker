"""Receipt checker web server. Standard library only.

    python3 server.py            # http://localhost:8000
    MOF_APP_ID=xxxx python3 server.py   # also use the official MoF API

Endpoints
  POST /api/check   {"code": "<scanned QR or barcode text>"}
                    {"number": "AB12345678", "date": "2025-09-14"}
                    -> parsed invoice, prize result, claim window
  GET  /api/winning?term=11410  -> winning numbers for a term
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import invoice as iv
import sources

STATIC = Path(__file__).with_name("static")


def check_payload(payload: dict, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    if payload.get("code"):
        inv = iv.parse_any(payload["code"])
    else:
        inv = iv.manual_invoice(payload.get("number", ""), payload.get("date", ""))
    sched = iv.term_schedule(inv.term)
    out = {"invoice": inv.to_dict(), "term_label": iv.term_label(inv.term),
           "schedule": sched}

    if dt.date.fromisoformat(sched["draw_date"]) > today:
        out["status"] = "not_drawn"
        out["message"] = f"Numbers for this period are drawn on {sched['draw_date']}."
        return out

    wn = sources.get_winning_numbers(inv.term)
    res = iv.check(inv, wn)
    out.update(result=res, winning_numbers=wn.__dict__)
    if not res["won"]:
        out["status"] = "no_win"
        out["message"] = "Not a winner this time."
    elif today > dt.date.fromisoformat(sched["claim_end"]):
        out["status"] = "expired"
        out["message"] = f"Won {res['prize']}, but the claim period ended {sched['claim_end']}."
    else:
        out["status"] = "won"
        out["message"] = (f"Winner! {res['prize']} NT${res['amount']:,}. "
                          f"Claim {sched['claim_start']} to {sched['claim_end']}.")

    app_id = os.environ.get("MOF_APP_ID")
    if app_id and payload.get("verify") and inv.encrypt:
        try:
            out["mof_detail"] = sources.query_invoice_detail(inv, app_id)
        except Exception as e:
            out["mof_detail_error"] = str(e)
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/winning":
            term = parse_qs(url.query).get("term", [None])[0]
            try:
                terms = [term] if term else iv.latest_drawn_terms()
                self._json(200, [sources.get_winning_numbers(t).__dict__ for t in terms])
            except Exception as e:
                self._json(502, {"error": str(e)})
            return
        name = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
        f = (STATIC / name).resolve()
        if STATIC.resolve() not in f.parents or not f.is_file():
            return self._json(404, {"error": "not found"})
        ctype = {".html": "text/html", ".js": "text/javascript",
                 ".css": "text/css"}.get(f.suffix, "application/octet-stream")
        self._send(200, f.read_bytes(), ctype + "; charset=utf-8")

    def do_POST(self):
        if urlparse(self.path).path != "/api/check":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
            self._json(200, check_payload(payload))
        except (ValueError, KeyError) as e:
            self._json(400, {"error": str(e)})
        except LookupError as e:
            self._json(502, {"error": str(e)})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8000))
    print(f"Receipt checker on http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
