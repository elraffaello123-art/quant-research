"""
kalshi_fetch.py — build the Kalshi settled-contract universe.

Replication target: Yang (2026), "Pricing Prediction Markets: Incomplete Markets,
Selection Rules, and Risk Premia" (SSRN 6468338), which estimates a Wang-transform
pricing wedge

    p_mkt = Phi( Phi^-1(p*) + lambda )

on 291,309 resolved contracts and reports lambda_CI = 0.178 on Kalshi.

The paper estimates lambda on hourly MID prices. Kalshi's public candlestick
endpoint also returns yes_bid and yes_ask, so we can re-estimate on the price a
taker could actually have hit. That is the whole point of this module: collect
the BOOK, not just the mid.

No auth required for these endpoints.

Stage 1 (this file):
  series   -> data/series.json          (category, fee_type, fee_multiplier)
  markets  -> data/markets_raw.jsonl    (settled markets in a close-time window)
  candles  -> data/candles/<ticker>.json (hourly yes_bid / yes_ask path)
"""

import json
import os
import sys
import time
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

API = "https://api.elections.kalshi.com/trade-api/v2"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CANDLES = os.path.join(DATA, "candles")

# Pure-randomness series the paper explicitly excludes: sub-hourly crypto
# up/down shards and the auto-generated multivariate cross-category baskets.
# These are ~87% of settled tickers by count and carry no forecasting content.
#
# Filter on the series' own `frequency` metadata, NOT on the ticker string: a
# regex for "1H" also catches KXLIGAPORTUGAL1H, KXEFLCUP1H etc., which are
# soccer FIRST-HALF markets and are perfectly good one-off contracts.
RANDOMNESS_PREFIXES = ("KXMVE",)
RANDOMNESS_FREQ = ("fifteen_min", "hourly")

_lock = threading.Lock()
_calls = [0]


_next_slot = [0.0]


RATE = float(os.environ.get("RATE", 10.0))


def _throttle(max_per_sec=None):
    """Global paced rate limit shared across worker threads.

    Sleeping 1/rate inside each thread would give rate*n_workers requests per
    second, not rate. Hand out timestamped slots under the lock instead, so the
    aggregate rate is what it says regardless of worker count. Kalshi's
    unauthenticated read tier is generous but a 429 storm costs more than it
    saves.
    """
    gap = 1.0 / (max_per_sec or RATE)
    with _lock:
        _calls[0] += 1
        now = time.time()
        slot = max(now, _next_slot[0])
        _next_slot[0] = slot + gap
    delay = slot - time.time()
    if delay > 0:
        time.sleep(delay)
    return _calls[0]


def get(path, tries=5):
    url = path if path.startswith("http") else f"{API}/{path}"
    for attempt in range(tries):
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kalshi-wedge-research/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            if e.code == 404:
                return None
            raise
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


def is_randomness(series_ticker, series_meta=None):
    if series_ticker.startswith(RANDOMNESS_PREFIXES):
        return True
    if series_meta:
        return series_meta.get("frequency") in RANDOMNESS_FREQ
    return False


# ---------------------------------------------------------------- stage 1a
def fetch_series():
    out = os.path.join(DATA, "series.json")
    if os.path.exists(out):
        return json.load(open(out))
    d = get("series?limit=200")
    series = {s["ticker"]: s for s in d["series"]}
    json.dump(series, open(out, "w"))
    print(f"series: {len(series)}")
    return series


# ---------------------------------------------------------------- stage 1b
def _volume(m):
    try:
        return float(m.get("volume_fp") or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_markets(min_volume=100, workers=6):
    """Fetch settled markets series-by-series.

    Paging the global /markets feed is hopeless: the auto-generated KXMVE
    cross-category shards are ~100% of the first pages. Iterating the 13.6k
    real series instead gives complete coverage of the tradeable universe in a
    bounded number of calls.

    min_volume=100 matches the paper's Kalshi filter (volume >= 100 contracts).
    """
    out = os.path.join(DATA, "markets_raw.jsonl")
    if os.path.exists(out):
        n = sum(1 for _ in open(out))
        print(f"markets_raw.jsonl exists: {n:,} rows (delete to refetch)")
        return out

    series = fetch_series()
    todo = [k for k, v in series.items() if not is_randomness(k, v)]
    print(f"fetching markets for {len(todo):,} series ({len(series)-len(todo)} randomness excluded)",
          flush=True)

    f = open(out, "w")
    stats = {"seen": 0, "kept": 0, "series_done": 0}
    t0 = time.time()

    def work(st):
        rows, cursor = [], None
        while True:
            u = f"markets?limit=1000&status=settled&series_ticker={st}"
            if cursor:
                u += f"&cursor={cursor}"
            try:
                d = get(u)
            except Exception:
                break
            if not d:
                break
            ms = d.get("markets", [])
            for m in ms:
                if m.get("result") not in ("yes", "no"):
                    continue
                if _volume(m) < min_volume:
                    continue
                m["_series"] = st
                m["_category"] = series[st].get("category")
                m["_fee_type"] = series[st].get("fee_type")
                m["_fee_multiplier"] = series[st].get("fee_multiplier")
                rows.append(m)
            cursor = d.get("cursor")
            if not cursor or not ms:
                break
        with _lock:
            stats["seen"] += 1
            stats["kept"] += len(rows)
            stats["series_done"] += 1
            for r in rows:
                f.write(json.dumps(r) + "\n")
            if stats["series_done"] % 500 == 0:
                el = time.time() - t0
                rate = stats["series_done"] / el
                eta = (len(todo) - stats["series_done"]) / rate / 60
                print(f"  series {stats['series_done']:,}/{len(todo):,}  "
                      f"markets kept {stats['kept']:,}  eta {eta:.0f}m", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, todo))
    f.close()
    print(f"markets: kept {stats['kept']:,} -> {out}")
    return out


# ---------------------------------------------------------------- stage 1c
def _iso_to_ts(s):
    import datetime
    s = s.replace("Z", "+00:00")
    return int(datetime.datetime.fromisoformat(s).timestamp())


def fetch_candles_one(m):
    tk = m["ticker"]
    dest = os.path.join(CANDLES, tk.replace("/", "_") + ".json")
    if os.path.exists(dest):
        return "cached"
    series = tk.split("-")[0]
    try:
        s = _iso_to_ts(m["open_time"])
        e = _iso_to_ts(m["close_time"])
    except Exception:
        return "badtime"
    if e <= s:
        return "badtime"
    # Pick the interval from the contract's span. Two hard constraints:
    #   - the API refuses (with a misleading HTTP 429) any request for more
    #     than 5000 candlesticks
    #   - the analysis needs >= 4 observations per contract, so a 15-minute
    #     crypto market is invisible at a 60-minute interval
    # Minute candles below a day, hourly up to ~200 days, daily beyond.
    span_h = (e - s) / 3600.0
    if span_h <= 24:
        interval = 1
    elif span_h <= 4000:
        interval = 60
    else:
        interval = 1440
    u = (f"series/{series}/markets/{tk}/candlesticks"
         f"?start_ts={s}&end_ts={e}&period_interval={interval}")
    try:
        d = get(u)
    except Exception as ex:
        return f"err:{ex}"
    if not d or not d.get("candlesticks"):
        return "empty"
    json.dump({"ticker": tk, "interval": interval, "candlesticks": d["candlesticks"]},
              open(dest, "w"))
    return "ok"


def sample_markets(ms, n, seed=7):
    """Stratified random sample by category, proportional to category size.

    The full settled universe is ~290k contracts, which at the API's sustainable
    rate is an overnight candle fetch for no statistical gain: the paper's
    N=199,671 gives SE(lambda)=0.004, so N=20,000 still gives SE~0.013 and a
    t-stat near 14 on lambda=0.178. Precision is not the binding constraint,
    and it lets the volume/duration/category cuts stay well populated.

    Random, not head-of-file: markets_raw.jsonl is written series-by-series, so
    the first N rows would be a handful of series rather than a cross-section.
    """
    import random
    if n >= len(ms):
        return list(ms)
    rng = random.Random(seed)
    by_cat = {}
    for m in ms:
        by_cat.setdefault(m.get("_category") or "Unknown", []).append(m)
    out = []
    for cat, rows in sorted(by_cat.items()):
        take = max(1, round(n * len(rows) / len(ms)))
        out.extend(rng.sample(rows, min(take, len(rows))))
    rng.shuffle(out)
    print(f"sampled {len(out):,} of {len(ms):,} markets across {len(by_cat)} categories")
    return out


def fetch_candles(markets_path, limit=None, sample=None, workers=6):
    os.makedirs(CANDLES, exist_ok=True)
    ms = [json.loads(l) for l in open(markets_path)]
    if sample:
        ms = sample_markets(ms, sample)
    if limit:
        ms = ms[:limit]
    print(f"candles: {len(ms):,} markets, {workers} workers", flush=True)
    counts = {}
    t0 = time.time()
    done = [0]

    def work(m):
        r = fetch_candles_one(m)
        key = r.split(":")[0]
        with _lock:
            counts[key] = counts.get(key, 0) + 1
            done[0] += 1
            if done[0] % 500 == 0:
                el = time.time() - t0
                rate = done[0] / el
                eta = (len(ms) - done[0]) / rate / 60
                print(f"  {done[0]:,}/{len(ms):,}  {rate:.1f}/s  eta {eta:.0f}m  {counts}",
                      flush=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, ms))
    print(f"candles done: {counts}")
    return counts


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage in ("all", "series"):
        fetch_series()
    if stage in ("all", "markets"):
        fetch_markets(min_volume=int(os.environ.get("MIN_VOLUME", 100)))
    if stage in ("all", "candles"):
        p = os.path.join(DATA, "markets_raw.jsonl")
        lim = os.environ.get("LIMIT")
        smp = os.environ.get("SAMPLE")
        fetch_candles(p, limit=int(lim) if lim else None,
                      sample=int(smp) if smp else None,
                      workers=int(os.environ.get("WORKERS", 6)))
