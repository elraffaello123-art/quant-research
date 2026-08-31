"""Robust volatility input: estimate sigma from the PREVIOUS full hour.

Why: estimating sigma from a short slice of the CURRENT hour lets the rule select on
its own estimation noise -- a quiet 135-second window drives sigma below any plausible
value, p_model pins to 1.00, and the rule bets hardest exactly where its input is
least trustworthy.

This uses 60 one-minute bars from the hour BEFORE the market's hour. Strictly prior
information, 60 observations instead of a noisy handful, and it cannot be contaminated
by the move the market is actually betting on.

sigma_per_second = stdev(1-minute log returns in bps) / sqrt(60)
"""
import os
import sys
import json
import math
import time
import statistics
import datetime as dt
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze as A


def fetch_prev_hour_sigma(symbol, end_epoch):
    """1-minute bars covering [end-7200, end-3600): the hour before this market's hour."""
    key = f"sigprev_{symbol}_{end_epoch}"
    cached = A.load(key)
    if cached is not None:
        return cached
    start = (end_epoch - 7200) * 1000
    url = (f"https://api.binance.com/api/v3/klines?symbol={symbol}"
           f"&interval=1m&startTime={start}&limit=60")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            k = json.loads(r.read())
    except Exception:
        k = []
    val = None
    if len(k) >= 30:
        closes = [float(x[4]) for x in k]
        rets = [math.log(b / a) * 1e4 for a, b in zip(closes, closes[1:]) if a > 0]
        if len(rets) >= 29:
            per_min = statistics.pstdev(rets)
            if per_min > 0:
                val = per_min / math.sqrt(60.0)      # bps per second
    with open(os.path.join(A.CACHE, key + ".json"), "w") as f:
        json.dump(val, f)
    return val


def main():
    ends = set()
    for fn in os.listdir(A.CACHE):
        if not fn.startswith("mkt_"):
            continue
        m = A.load(fn[:-5])
        if not m or m.get("vol", 0) < 500:
            continue
        asset = fn[4:].split("-up-or-down")[0]
        sym = A.ASSETS.get(asset)
        if not sym:
            continue
        end = int(dt.datetime.fromisoformat(
            m["endDate"].replace("Z", "+00:00")).timestamp())
        ends.add((sym, end))
    print(f"{len(ends)} market-hours need a prior-hour sigma")
    got = []
    for i, (sym, end) in enumerate(sorted(ends)):
        v = fetch_prev_hour_sigma(sym, end)
        if v:
            got.append(v)
        if i % 50 == 0:
            print(f"  {i}/{len(ends)}", flush=True)
        time.sleep(0.03)
    got.sort()
    if got:
        print(f"\nprior-hour sigma (bps/sec), n={len(got)}")
        print(f"  min {got[0]:.3f}  p10 {got[len(got)//10]:.3f}  "
              f"median {statistics.median(got):.3f}  p90 {got[-max(1,len(got)//10)]:.3f}  max {got[-1]:.3f}")
        print(f"  implied median 1h move: {statistics.median(got)*60:.1f} bps")


if __name__ == "__main__":
    main()
