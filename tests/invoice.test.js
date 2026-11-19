// Same cases as tests/test_invoice.py, run against static/invoice.js.
// Run: node --test "tests/*.test.js"
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as iv from "../static/invoice.js";

// Synthetic numbers only, NOT real draw results.
const WN = { term: "11410", special: "12345678", grand: "87654321",
             first: ["11122233", "44455566", "77788899"], additional_sixth: ["135"] };

const hex8 = n => n.toString(16).padStart(8, "0");
function leftQr({ number = "AB11122233", date = "1140914", rand = "1234", sales = 95, total = 100,
                  buyer = "00000000", seller = "12345675",
                  tail = ":**********:2:2:1:咖啡:1:60:麵包:1:40" } = {}) {
  return number + date + rand + hex8(sales) + hex8(total) + buyer + seller + "A".repeat(24) + tail;
}

test("left QR", () => {
  const inv = iv.parseLeftQr(leftQr());
  assert.equal(inv.number, "AB11122233");
  assert.equal(inv.date, "2025-09-14");
  assert.deepEqual([inv.sales_amount, inv.total_amount], [95, 100]);
  assert.equal(inv.seller_id, "12345675");
  assert.deepEqual(inv.items.map(i => i.name), ["咖啡", "麵包"]);
  assert.equal(inv.term, "11410");
});

test("base64 item names", () => {
  const inv = iv.parseLeftQr(leftQr({ tail: ":**********:1:1:2:5ZKW5ZWh:1:60" }));
  assert.equal(inv.items[0].name, "咖啡");
});

test("barcode", () => {
  const inv = iv.parseBarcode("11410AB111222331234");
  assert.deepEqual([inv.number, inv.term, inv.random_code], ["AB11122233", "11410", "1234"]);
});

test("rejects the right-hand QR", () => {
  assert.throws(() => iv.parseAny("**:咖啡:1:60"));
});

test("manual entry", () => {
  assert.equal(iv.manualInvoice("ab-11122233", "2025-10-02").number, "AB11122233");
  assert.equal(iv.manualInvoice("11122233", "2025-10-02").digits, "11122233");
  assert.throws(() => iv.manualInvoice("AB1112223", "2025-10-02"));
  assert.throws(() => iv.manualInvoice("AB11122233", ""));
});

test("term for a date", () => {
  assert.equal(iv.termFor("2025-01-31"), "11402");
  assert.equal(iv.termFor("2025-12-01"), "11412");
  assert.equal(iv.termLabel("11508"), "115年07-08月");
});

test("schedule crosses the year", () => {
  assert.deepEqual(iv.termSchedule("11412"),
    { draw_date: "2026-01-25", claim_start: "2026-02-06", claim_end: "2026-05-05" });
});

test("latest drawn terms", () => {
  assert.deepEqual(iv.latestDrawnTerms("2026-11-19"), ["11508", "11506"]);
  assert.deepEqual(iv.latestDrawnTerms("2026-11-26"), ["11510", "11508"]);
});

const chk = digits => iv.check(iv.manualInvoice("AB" + digits, "2025-09-01"), WN);

test("every prize tier", () => {
  const cases = { "12345678": 10_000_000, "87654321": 2_000_000, "11122233": 200_000,
                  "01122233": 40_000, "00122233": 10_000, "00022233": 4_000,
                  "00002233": 1_000, "00000233": 200, "00000135": 200, "00000000": 0 };
  for (const [digits, amount] of Object.entries(cases))
    assert.equal(chk(digits).amount, amount, digits);
});

test("special prize needs all 8 digits", () => {
  assert.equal(chk("02345678").amount, 0);
});

test("wrong term", () => {
  assert.throws(() => iv.check(iv.manualInvoice("AB11122233", "2025-05-01"), WN));
});

test("end to end: scanned winner", () => {
  const out = iv.checkPayload({ code: leftQr() }, [WN], "2025-12-01");
  assert.deepEqual([out.status, out.result.amount], ["won", 200_000]);
  assert.equal(out.schedule.claim_end, "2026-03-05");
});

test("end to end: expired", () => {
  assert.equal(iv.checkPayload({ code: leftQr() }, [WN], "2026-04-01").status, "expired");
});

test("end to end: not drawn yet", () => {
  const out = iv.checkPayload({ number: "AB11122233", date: "2025-10-02" }, [WN], "2025-11-01");
  assert.equal(out.status, "not_drawn");
});

test("end to end: drawn but numbers not loaded yet stays pending", () => {
  const out = iv.checkPayload({ number: "AB11122233", date: "2025-10-02" }, [], "2025-11-26");
  assert.equal(out.status, "not_drawn");
});

test("end to end: loser", () => {
  const out = iv.checkPayload({ number: "AB00000000", date: "2025-10-02" }, [WN], "2025-12-01");
  assert.equal(out.status, "no_win");
});

test("committed winning.json has the expected shape", () => {
  const data = JSON.parse(readFileSync(new URL("../static/winning.json", import.meta.url), "utf8"));
  assert.ok(Array.isArray(data.terms) && data.terms.length > 0);
  for (const t of data.terms) {
    assert.match(t.term, /^\d{5}$/);
    assert.match(t.special, /^\d{8}$/);
    assert.match(t.grand, /^\d{8}$/);
    assert.ok(t.first.length >= 3 && t.first.every(f => /^\d{8}$/.test(f)));
  }
});
