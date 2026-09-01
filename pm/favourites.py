"""
favourites.py — can you buy the favourite side?

Three claims, tested on the same Kalshi data as wedge.py:

  1. "Buy contracts priced at 91c where the true probability is higher."
  2. "Buy 99c contracts."
  3. Lee, Lee & Lee (2026), SSRN 6748186: prediction markets are "systematically
     underconfident" — prices pulled toward 0.50, so favourites are underpriced.

All three are the same trade as selling the longshot, because YES + NO = 1.
wedge.py already answered it at the mid; this file answers it at the ask, and
adds the one thing that turns out to decide the 99c case: Kalshi rounds its fee
UP to the cent.

It also carries a correction. wedge.py's headline (lambda = +0.036 at the mid)
was computed on a panel that admitted books quoted 0.02 / 0.98 — no bid, no
offer, just a placeholder. Those are not books, and they carry the entire
positive wedge. Restricted to books with a real two-sided quote, the mid-price
wedge is zero or negative. See `book_quality()`.
"""

import glob
import json
import math
import os

import numpy as np

import wedge as W

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def load(markets_file="markets_raw.jsonl", require_two_sided=True):
    """Panel of opening quotes.

    require_two_sided drops books with no bid or no offer. wedge.py only
    dropped the degenerate 0.00/1.00 case, which let 0.02/0.98 through — and a
    0.02/0.98 quote is an empty book wearing a 98-cent costume, not a favourite.
    """
    markets = {}
    for line in open(os.path.join(DATA, markets_file)):
        m = json.loads(line)
        markets[m["ticker"]] = m

    rows = []
    for tk, m in markets.items():
        fp = os.path.join(DATA, "candles", tk.replace("/", "_") + ".json")
        if not os.path.exists(fp):
            continue
        try:
            c = json.load(open(fp))
        except Exception:
            continue
        cs = c.get("candlesticks") or []
        if len(cs) < 4:
            continue
        try:
            t0, t1 = W._iso_ts(m["open_time"]), W._iso_ts(m["close_time"])
        except Exception:
            continue
        if t1 <= t0:
            continue
        path = []
        for k in cs:
            ts = k.get("end_period_ts")
            b = W._f(k.get("yes_bid") or {}, "close_dollars")
            a = W._f(k.get("yes_ask") or {}, "close_dollars")
            if ts is None or b is None or a is None or a <= b:
                continue
            if require_two_sided and (b <= 0.0 or a >= 1.0):
                continue
            if not require_two_sided and (b <= 0.0 and a >= 1.0):
                continue
            path.append((ts, b, a))
        if len(path) < 4:
            continue
        cutoff = t0 + W.OPEN_TAU * (t1 - t0)
        ts, b, a = next((p for p in path if p[0] >= cutoff), path[0])
        rows.append({"bid": b, "ask": a, "mid": 0.5 * (b + a), "sp": a - b,
                     "y": 1 if m["result"] == "yes" else 0,
                     "cat": m.get("_category")})
    return rows


def arrays(rows):
    return (np.array([r["bid"] for r in rows]), np.array([r["ask"] for r in rows]),
            np.array([r["mid"] for r in rows]), np.array([r["sp"] for r in rows]),
            np.array([r["y"] for r in rows]))


# ------------------------------------------------------------------ the fee
def breakeven_table():
    """Why the 99c trade is not a close call.

    Kalshi's fee is 0.07*C*p*(1-p) ROUNDED UP TO THE CENT. At p=0.99 the raw
    fee is 0.07c and the charge is 1.00c, so total cost is exactly $1.00 — the
    contract's maximum payoff. Max profit is zero with 99c still at risk. No
    forecasting edge can repair that; it is arithmetic, not a probability
    question.
    """
    print("BUY THE FAVOURITE AT p, HOLD TO SETTLEMENT (fee rounded UP to the cent)")
    print(f"{'price':>7s} {'raw fee':>9s} {'CHARGED':>9s} {'cost':>8s} "
          f"{'max profit':>11s} {'breakeven win%':>15s}")
    for p in (0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.98, 0.99):
        raw = 0.07 * p * (1 - p)
        f = math.ceil(raw * 100) / 100.0
        cost = p + f
        flag = "   <-- IMPOSSIBLE" if cost >= 1.0 else ""
        print(f"  {p:5.2f} {raw*100:8.3f}c {f*100:8.2f}c {cost*100:7.2f}c "
              f"{(1.0-cost)*100:+10.2f}c {cost*100:14.2f}%{flag}")


# ------------------------------------------------------------- the evidence
def buy_favourite(bid, ask, mid, sp, y, max_spread=0.05, label=""):
    print(f"\nBUY AT THE ASK, books with spread <= {max_spread*100:.0f}c {label}")
    print(f"{'ask band':>13s} {'N':>6s} {'win%':>8s} {'ask':>8s} "
          f"{'gross':>8s} {'fee':>6s} {'net':>8s}")
    tight = sp <= max_spread
    for lo, hi in ((0.80, 0.85), (0.85, 0.90), (0.90, 0.93),
                   (0.93, 0.96), (0.96, 0.98), (0.98, 1.0)):
        m = tight & (ask >= lo) & (ask < hi)
        n = int(m.sum())
        if n < 25:
            print(f"  {lo:.2f}-{hi:.2f}   {n:6d}   (too few)")
            continue
        wr = y[m].mean()
        cost = ask[m]
        fee = np.array([W.kalshi_fee(p) for p in cost])
        net = y[m] * 1.0 - cost - fee
        print(f"  {lo:.2f}-{hi:.2f}   {n:6d} {wr*100:7.2f}% {cost.mean()*100:7.2f}c "
              f"{(wr-cost.mean())*100:+7.2f}c {fee.mean()*100:5.2f}c {net.mean()*100:+7.2f}c")


def book_quality(bid, ask, mid, sp, y):
    """The correction: the positive mid-price wedge lives only in non-books."""
    print("\nlambda BY BOOK QUALITY — the wide 'books' are not books")
    for lab, msk in (("spread <= 2c", sp <= 0.02), ("spread <= 5c", sp <= 0.05),
                     ("spread <=10c", sp <= 0.10), ("spread > 10c", sp > 0.10)):
        if msk.sum() < 100:
            continue
        q, z = W.complement_invariant(mid[msk], y[msk])
        l1, s1, n1 = W.wang_mle(q, z)
        qe, ze = W.executable_fold(bid[msk], ask[msk], y[msk])
        l2, s2, _ = W.wang_mle(qe, ze)
        print(f"  {lab}  N={n1:6,}   mid={l1:+.4f} (t={l1/s1:+6.2f})   "
              f"exec={l2:+.4f} (t={l2/s2:+7.2f})")


if __name__ == "__main__":
    breakeven_table()

    rows = load()
    b, a, m, s, y = arrays(rows)
    print(f"\n\nmain panel, genuinely two-sided books: {len(rows):,}  "
          f"median spread {np.median(s)*100:.1f}c")
    book_quality(b, a, m, s, y)
    buy_favourite(b, a, m, s, y, label="(all categories)")

    if os.path.exists(os.path.join(DATA, "markets_randomness.jsonl")):
        rows2 = load("markets_randomness.jsonl")
        b2, a2, m2, s2, y2 = arrays(rows2)
        print(f"\n\ncrypto/randomness panel: {len(rows2):,}  "
              f"median spread {np.median(s2)*100:.1f}c  "
              f"(the tightest books on the venue)")
        print("\nAt the MID — this is what a paper without book data measures:")
        for lo, hi in ((0.55, 0.75), (0.75, 0.95)):
            msk = (m2 >= lo) & (m2 < hi)
            if msk.sum() < 25:
                continue
            print(f"  mid {lo:.2f}-{hi:.2f}: N={int(msk.sum()):5d}  "
                  f"win%={y2[msk].mean()*100:6.2f}%  mid={m2[msk].mean()*100:6.2f}c  "
                  f"gross={(y2[msk].mean()-m2[msk].mean())*100:+6.2f}c")
        buy_favourite(b2, a2, m2, s2, y2, label="(crypto only)")
