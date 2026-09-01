"""
calibration.py — a reliability diagram is a weighting choice, not a fact.

Lee, Lee & Lee (2026, SSRN 6748186) Figure 4 shows Kalshi and Polymarket
reliability diagrams with a pronounced S-shape: on the Kalshi panel, contracts
priced near 0.35 resolve yes about 9% of the time and contracts priced near
0.65 resolve yes about 89%. Read literally that is a ~24-cent edge, which no
functioning book could carry.

Their diagrams pool transactions: 35.9M Kalshi trades across 40,874 contracts
(median 131 per contract), and 240.8M Polymarket trades across 72,464 (median
2,032). A contract with 10,000 trades enters the histogram 10,000 times.

This module rebuilds the same diagram from Kalshi quote paths three ways:

  A. one observation per contract, at 5% of life
  B. every time point pooled, each counting once  (what trade-pooling approximates)
  C. every time point pooled, but REWEIGHTED so each contract counts once

A and C agree and show a well-calibrated book. B shows 5-8 percentage points of
systematic miscalibration that exists only because path length is heavily
skewed: median 14 observations, p99 162, max 858, so the top 1% of contracts
supply 17.6% of all pooled observations and the top 10% supply 42.2%.

The mechanism is NOT a yes/no asymmetry in contract lifetime — contracts ending
no contribute 1.03x the observations of contracts ending yes, which is nothing.
It is pure dispersion in path length.

Caveat, stated plainly: the artifact demonstrated here has the OPPOSITE sign to
the paper's curve, and the paper pools trades where this pools quotes. This does
not prove their figure is this artifact. It proves something weaker and still
decisive — a transaction-weighted reliability diagram is not evidence about
whether contracts at a given price are correctly priced.
"""

import json
import os

import numpy as np

import wedge as W

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_paths(markets_file="markets_randomness.jsonl"):
    markets = {}
    for line in open(os.path.join(DATA, markets_file)):
        m = json.loads(line)
        markets[m["ticker"]] = m

    out = []
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
            if b <= 0.0 or a >= 1.0:
                continue
            path.append((ts, 0.5 * (b + a)))
        if len(path) < 4:
            continue
        out.append({"y": 1 if m["result"] == "yes" else 0,
                    "path": path, "t0": t0, "t1": t1})
    return out


def table(rows, bins=((0.2, 0.3), (0.3, 0.4), (0.4, 0.5),
                      (0.5, 0.6), (0.6, 0.7), (0.7, 0.8))):
    p, y, w = [], [], []
    for r in rows:
        wt = 1.0 / len(r["path"])
        for _, mid in r["path"]:
            p.append(mid)
            y.append(r["y"])
            w.append(wt)
    p, y, w = np.array(p), np.array(y), np.array(w)
    npath = np.array([len(r["path"]) for r in rows])

    print(f"contracts {len(rows):,}   pooled observations {len(p):,}")
    order = np.argsort(-npath)
    tot = npath.sum()
    top1 = npath[order[:max(1, len(npath)//100)]].sum() / tot * 100
    top10 = npath[order[:max(1, len(npath)//10)]].sum() / tot * 100
    print(f"path length per contract: median {np.median(npath):.0f}, "
          f"p99 {np.percentile(npath,99):.0f}, max {npath.max()}")
    print(f"  top 1% of contracts supply {top1:.1f}% of pooled observations; "
          f"top 10% supply {top10:.1f}%")

    print(f"\n{'bin':>10s} {'N obs':>8s} {'mean pred':>10s} "
          f"{'realized OBS-wt':>16s} {'realized CONTRACT-wt':>21s}")
    for lo, hi in bins:
        m = (p >= lo) & (p < hi)
        if m.sum() < 50:
            continue
        print(f"  {lo:.1f}-{hi:.1f} {int(m.sum()):8d} {p[m].mean():10.3f} "
              f"{y[m].mean():16.3f} {np.average(y[m], weights=w[m]):21.3f}")

    ny = npath[np.array([r["y"] for r in rows]) == 1]
    nn = npath[np.array([r["y"] for r in rows]) == 0]
    print(f"\nlifetime asymmetry check (is one outcome lingering?):")
    print(f"  ending yes: mean {ny.mean():.1f} observations")
    print(f"  ending no : mean {nn.mean():.1f} observations   "
          f"ratio {nn.mean()/ny.mean():.2f}x — not the mechanism")


if __name__ == "__main__":
    rows = load_paths()
    table(rows)
