"""
binance_fetch.py — underlying price paths for the hedged-VRP test.

Kalshi's 15-minute crypto contracts settle on an index, but Binance spot is the
dominant venue and is the practical hedging instrument. data.binance.vision
serves free daily kline zips, no auth.

1-second klines: a 15-minute contract gives 900 hedge opportunities, which lets
hedge frequency be a parameter of the test rather than an assumption. That
matters here — the whole question is whether a digital's gamma near the strike
makes the hedge unaffordable.
"""

import io
import json
import os
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
BARS = os.path.join(DATA, "binance")

BASE = "https://data.binance.vision/data/spot/daily/klines"

SERIES_TO_SYMBOL = {
    "KXBTC15M": "BTCUSDT", "KXETH15M": "ETHUSDT", "KXSOL15M": "SOLUSDT",
    "KXXRP15M": "XRPUSDT", "KXBNB15M": "BNBUSDT", "KXNEAR15M": "NEARUSDT",
    "KXZEC15M": "ZECUSDT", "KXDOGE15M": "DOGEUSDT",
}


def fetch_one(sym, day, interval="1s"):
    dest = os.path.join(BARS, f"{sym}-{interval}-{day}.csv")
    if os.path.exists(dest):
        return "cached"
    url = f"{BASE}/{sym}/{interval}/{sym}-{interval}-{day}.zip"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "vrp-research/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            blob = r.read()
    except Exception as e:
        return f"err:{type(e).__name__}"
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
        name = z.namelist()[0]
        with open(dest, "wb") as f:
            f.write(z.read(name))
    except Exception as e:
        return f"badzip:{e}"
    return "ok"


def main(interval="1s"):
    os.makedirs(BARS, exist_ok=True)
    need = json.load(open(os.path.join(DATA, "binance_need.json")))
    jobs = [(s, d) for s in need["symbols"] for d in need["days"]]
    print(f"{len(jobs)} files ({len(need['symbols'])} symbols x {len(need['days'])} days), {interval}")
    res = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(lambda j: fetch_one(j[0], j[1], interval), jobs):
            k = r.split(":")[0]
            res[k] = res.get(k, 0) + 1
    print(res)
    tot = sum(os.path.getsize(os.path.join(BARS, f)) for f in os.listdir(BARS))
    print(f"total on disk: {tot/1e6:.0f} MB")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "1s")
