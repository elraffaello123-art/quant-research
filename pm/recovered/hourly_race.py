"""Is there a speed edge in Polymarket's hourly crypto up/down markets?

THE SETUP
---------
Markets like `bitcoin-up-or-down-august-29-2026-3pm-et` resolve:
    "Up if the CLOSE price >= the OPEN price of the BTC/USDT 1 hour candle"
Resolution source is BINANCE. That feed is free, public, and ~1ms away over a
websocket. So there is no privileged data here -- only a race to act on a fact
that is already public.

THE QUESTION
------------
In the final seconds of the hour, Binance spot vs the candle open already tells you
the answer with high confidence. Does the Polymarket price reflect that? Where it
doesn't, how many dollars are on the table?

WHAT IS MEASURED
----------------
1. CALIBRATION (no decision rule, no lookahead): bucket every trade by the price it
   printed at and by seconds-remaining, then report how often it actually resolved
   Up. If PM pays 0.96 with 10s left and resolves Up 99% of the time, that gap is
   the edge, visible with no model at all.
2. A SPOT RULE evaluated honestly: decide only from spot at or before the trade's
   timestamp, never from the outcome. Buy the side spot favours when PM offers it
   below our confidence. P&L against the realised outcome, net of the taker fee.
3. NULL: the same rule with the spot input REMOVED (bet the side PM already favours).
   A calibrated book makes this ~0. If the spot rule doesn't beat this null, the
   "edge" was just the book being right and us riding along.

HONESTY NOTES -- read before believing any number
-------------------------------------------------
* FILL FICTION. We assume we could have taken the print that actually happened. In
  reality we'd be racing other bots for that same fill. Every P&L here is an UPPER
  BOUND, not an achievable number. Same class of error as filling at the level
  instead of the next open.
* Spot is read from the CLOSE OF THE PREVIOUS SECOND, never the current one, so the
  decision is strictly non-anticipating.
* PM timestamps are unix SECONDS. No sub-second structure is visible.
* Trade side is not in the tape; direction is never inferred from the outcome.
"""
import sys
import json
import time
import os
import datetime as dt
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pmnet

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE, exist_ok=True)

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
ASSETS = {"bitcoin": "BTCUSDT", "ethereum": "ETHUSDT", "solana": "SOLUSDT"}

DAYS_BACK = int(os.environ.get("DAYS_BACK", "30"))
END_DATE = dt.date(2026, 8, 29)      # last fully-resolved day
LOOKBACK_SEC = 600                    # how far before the close we study
FEE_RATE = 0.07                       # crypto taker fee: 0.07 * p * (1-p)


def cached(key, fn):
    path = os.path.join(CACHE, key.replace("/", "_") + ".json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    val = fn()
    with open(path, "w") as f:
        json.dump(val, f)
    return val


# ------------------------------------------------------------------ polymarket

def hour_slug(asset, d, hour_et):
    hr = 12 if hour_et % 12 == 0 else hour_et % 12
    ap = "am" if hour_et < 12 else "pm"
    return f"{asset}-up-or-down-{MONTHS[d.month-1]}-{d.day}-{d.year}-{hr}{ap}-et"


def get_market(slug):
    def fetch():
        try:
            r = pmnet.get(f"https://gamma-api.polymarket.com/markets?slug={slug}&closed=true")
        except Exception:
            return None
        if not r:
            return None
        m = r[0]
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            prices = json.loads(prices)
        if not prices or prices[0] not in ("1", "0"):
            return None                      # not cleanly resolved -- skip
        return {"cid": m["conditionId"], "endDate": m["endDate"],
                "up": prices[0] == "1", "vol": float(m.get("volumeNum") or 0)}
    return cached("mkt_" + slug, fetch)


def get_tape(cid):
    def fetch():
        rows, off = [], 0
        while off < 3000:
            try:
                c = pmnet.get(f"https://data-api.polymarket.com/trades?market={cid}&limit=500&offset={off}")
            except Exception:
                break
            if not c:
                break
            for t in c:
                try:
                    p = float(t["price"])
                    if t.get("outcome") == "Down":
                        p = 1.0 - p
                    rows.append([int(t["timestamp"]), p, float(t.get("size") or 0)])
                except (KeyError, TypeError, ValueError):
                    continue
            if len(c) < 500:
                break
            off += 500
        return sorted(rows)
    return cached("tape_" + cid[:20], fetch)


# --------------------------------------------------------------------- binance

def binance(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def get_hour(symbol, end_epoch):
    """(open_price, close_price) of the 1h candle ENDING at end_epoch, plus the
    per-second close series for the final LOOKBACK_SEC of that hour."""
    def fetch():
        start = (end_epoch - 3600) * 1000
        k = binance(f"https://api.binance.com/api/v3/klines?symbol={symbol}"
                    f"&interval=1h&startTime={start}&limit=1")
        if not k:
            return None
        time.sleep(0.05)
        s2 = (end_epoch - LOOKBACK_SEC) * 1000
        ks = binance(f"https://api.binance.com/api/v3/klines?symbol={symbol}"
                     f"&interval=1s&startTime={s2}&endTime={end_epoch*1000}&limit=1000")
        return {"open": float(k[0][1]), "close": float(k[0][4]),
                "secs": {str(int(r[0] // 1000)): float(r[4]) for r in ks}}
    return cached(f"bnc_{symbol}_{end_epoch}", fetch)


# ----------------------------------------------------------------------- study

def build():
    recs = []
    for asset, symbol in ASSETS.items():
        n_mkt = 0
        for back in range(DAYS_BACK):
            day = END_DATE - dt.timedelta(days=back)
            for hour in range(24):
                m = get_market(hour_slug(asset, day, hour))
                if not m or m["vol"] < 500:
                    continue
                end = int(dt.datetime.fromisoformat(
                    m["endDate"].replace("Z", "+00:00")).timestamp())
                bн = get_hour(symbol, end)
                if not bн or not bн["secs"]:
                    continue
                # sanity: Binance must agree with how the market actually resolved
                if (bн["close"] >= bн["open"]) != m["up"]:
                    continue
                n_mkt += 1
                secs = bн["secs"]
                for ts, p, sz in get_tape(m["cid"]):
                    left = end - ts
                    if not (0 <= left <= LOOKBACK_SEC) or sz <= 0:
                        continue
                    spot = secs.get(str(ts - 1)) or secs.get(str(ts - 2))
                    if not spot:
                        continue
                    recs.append({
                        "asset": asset, "left": left, "p": p, "size": sz,
                        "up": m["up"],
                        "bps": (spot - bн["open"]) / bн["open"] * 1e4,
                    })
            print(f"  {asset:9s} day -{back:<3d} markets={n_mkt} trades={len(recs)}", flush=True)
    return recs


def fee(p):
    return FEE_RATE * p * (1.0 - p)


def report(recs):
    print(f"\n{'='*76}\nSAMPLE: {len(recs)} trades in the final {LOOKBACK_SEC}s of resolved hours")
    if not recs:
        print("no data -- stopping rather than reporting a number")
        return

    print(f"\n{'='*76}\n1. CALIBRATION  (no model, no lookahead)\n{'='*76}")
    print("   is the PM price honest about what actually happens?")
    for lo, hi, lab in [(0, 15, "0-15s"), (15, 60, "15-60s"), (60, 180, "60-180s"), (180, 600, "180-600s")]:
        print(f"\n   -- {lab} before close --")
        print(f"   {'PM price':>12} {'n':>7} {'$ size':>12} {'realised Up':>13} {'gap':>9}")
        for plo, phi in [(0, .05), (.05, .2), (.2, .4), (.4, .6), (.6, .8), (.8, .95), (.95, 1.0)]:
            b = [r for r in recs if lo <= r["left"] < hi and plo <= r["p"] < phi]
            if len(b) < 20:
                continue
            w = sum(r["size"] for r in b)
            realised = sum(r["size"] for r in b if r["up"]) / w
            mean_p = sum(r["p"] * r["size"] for r in b) / w
            print(f"   {plo:.2f}-{phi:<7.2f}{len(b):>7}{w:>12,.0f}{realised:>13.3f}{realised-mean_p:>+9.3f}")

    print(f"\n{'='*76}\n2. SPOT RULE vs NULL   (decision from spot only, never the outcome)\n{'='*76}")
    print(f"   {'window':>10} {'bps gate':>9} {'n':>7} {'$ staked':>11} {'rule P&L':>11} {'null P&L':>11} {'edge/$':>9}")
    for lo, hi, lab in [(0, 15, "0-15s"), (15, 60, "15-60s"), (60, 180, "60-180s"), (180, 600, "180-600s")]:
        for gate in (5, 15, 40):
            rule = null = staked = 0.0
            n = 0
            for r in recs:
                if not (lo <= r["left"] < hi) or abs(r["bps"]) < gate:
                    continue
                believe_up = r["bps"] > 0
                px = r["p"] if believe_up else 1.0 - r["p"]
                if px > 0.97:                       # nothing left to win
                    continue
                won = (r["up"] == believe_up)
                rule += r["size"] * ((1.0 if won else 0.0) - px - fee(px))
                # null: same stake, but side chosen by the BOOK not by spot
                nb = r["p"] > 0.5
                npx = r["p"] if nb else 1.0 - r["p"]
                null += r["size"] * ((1.0 if (r["up"] == nb) else 0.0) - npx - fee(npx))
                staked += r["size"] * px
                n += 1
            if n >= 30:
                print(f"   {lab:>10}{gate:>9}{n:>7}{staked:>11,.0f}"
                      f"{rule:>11,.0f}{null:>11,.0f}{rule/staked:>+9.3f}")

    print("\nreminder: every P&L above is an UPPER BOUND -- it assumes we win the race")
    print("for prints that actually happened. it is not an achievable number.")


if __name__ == "__main__":
    t0 = time.time()
    recs = build()
    print(f"\nbuilt in {time.time()-t0:.0f}s")
    report(recs)
