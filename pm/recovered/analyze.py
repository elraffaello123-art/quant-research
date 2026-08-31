"""Does Binance spot price the hourly up/down market better than Polymarket does?

MODEL (zero fitted parameters -- nothing to overfit)
----------------------------------------------------
The contract asks: will the Binance close at time T be >= the hour's open?
Under a driftless random walk with per-second vol sigma:

    P(Up) = Phi( d / (sigma * sqrt(tau)) )

  d    = current distance from the hour open, in bps  (Binance, strictly prior second)
  tau  = seconds remaining in the hour
  sigma= realised per-second vol in bps, estimated ONLY from seconds strictly
         before this trade, expanding window, minimum 60 observations.

No parameter is fitted to outcomes. Sigma is measured, not tuned.

THE TEST
--------
* Trade only when |p_model - p_pm| exceeds a threshold: PM disagrees with what
  spot already implies. Take the side the model favours, at PM's printed price,
  net of the taker fee.
* OUT-OF-SAMPLE: the model has no parameters, but the THRESHOLD is a choice, so
  the sample is split by date -- thresholds are read off the older half, the
  reported number comes from the newer half.
* PERMUTATION NULL: shuffle which hour's OUTCOME belongs to which hour's trades,
  200 times, and re-run the whole thing. If the real P&L sits inside that
  distribution, there is no edge -- only a lucky path. This is the check that
  killed the ORB meta-labeling.

STILL AN UPPER BOUND
--------------------
We assume we could have taken the prints that actually happened. In reality we
would be racing other bots for those same fills. Treat every P&L as a ceiling.
"""
import os
import sys
import json
import math
import random
import statistics
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
ASSETS = {"bitcoin": "BTCUSDT", "ethereum": "ETHUSDT", "solana": "SOLUSDT"}
FEE_RATE = 0.07
MIN_VOL_OBS = 60
SEED = 20260830


def load(name):
    p = os.path.join(CACHE, name + ".json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fee(p):
    return FEE_RATE * p * (1.0 - p)


def build():
    """Reassemble records from cache only -- no network."""
    recs = []
    for asset, symbol in ASSETS.items():
        for fn in os.listdir(CACHE):
            if not fn.startswith(f"mkt_{asset}-up-or-down-"):
                continue
            m = load(fn[:-5])
            if not m or m.get("vol", 0) < 500:
                continue
            end = int(dt.datetime.fromisoformat(
                m["endDate"].replace("Z", "+00:00")).timestamp())
            bn = load(f"bnc_{symbol}_{end}")
            if not bn or not bn.get("secs"):
                continue
            if (bn["close"] >= bn["open"]) != m["up"]:
                continue
            tape = load("tape_" + m["cid"][:20])
            if not tape:
                continue
            secs = {int(k): v for k, v in bn["secs"].items()}
            ordered = sorted(secs)
            # per-second log returns, in bps, keyed by the second they END on
            rets = {}
            for a, b in zip(ordered, ordered[1:]):
                if b - a == 1 and secs[a] > 0:
                    rets[b] = math.log(secs[b] / secs[a]) * 1e4
            for ts, p, sz in tape:
                tau = end - ts
                if not (1 <= tau <= 600) or sz <= 0 or not (0.0 < p < 1.0):
                    continue
                spot = secs.get(ts - 1) or secs.get(ts - 2)
                if not spot:
                    continue
                prior = [r for s, r in rets.items() if s < ts]   # strictly before
                if len(prior) < MIN_VOL_OBS:
                    continue
                sigma = statistics.pstdev(prior)
                if sigma <= 0:
                    continue
                d = (spot - bn["open"]) / bn["open"] * 1e4
                recs.append({
                    "asset": asset, "end": end, "tau": tau, "p_pm": p, "size": sz,
                    "up": bool(m["up"]), "d": d, "sigma": sigma,
                    "p_mod": norm_cdf(d / (sigma * math.sqrt(tau))),
                })
    recs.sort(key=lambda r: r["end"])
    return recs


def run_rule(recs, thresh, outcome_map=None):
    """P&L of: bet when the model disagrees with PM by more than `thresh`.
    outcome_map lets the permutation null substitute shuffled outcomes."""
    pnl = staked = 0.0
    n = 0
    for r in recs:
        edge = r["p_mod"] - r["p_pm"]
        if abs(edge) < thresh:
            continue
        buy_up = edge > 0                      # model says Up is underpriced
        px = r["p_pm"] if buy_up else 1.0 - r["p_pm"]
        if px <= 0.001 or px >= 0.99:
            continue
        up = outcome_map[r["end"]] if outcome_map else r["up"]
        won = 1.0 if (up == buy_up) else 0.0
        pnl += r["size"] * (won - px - fee(px))
        staked += r["size"] * px
        n += 1
    return pnl, staked, n


def main():
    recs = build()
    if len(recs) < 500:
        print(f"only {len(recs)} usable trades -- collection still running, stopping here")
        return
    days = sorted({dt.datetime.utcfromtimestamp(r["end"]).date() for r in recs})
    print(f"{len(recs):,} trades | {len(days)} days {days[0]} -> {days[-1]} | "
          f"{len({r['end'] for r in recs})} hourly markets")

    # ---- calibration: does PM's price match what actually happens?
    print(f"\n{'='*78}\nCALIBRATION  (PM price vs realised frequency, size-weighted)\n{'='*78}")
    print(f"{'tau':>10} {'PM price':>12} {'n':>7} {'$ size':>12} {'realised':>10} "
          f"{'PM gap':>9} {'model gap':>10}")
    for lo, hi, lab in [(1, 15, "1-15s"), (15, 60, "15-60s"),
                        (60, 180, "60-180s"), (180, 600, "180-600s")]:
        for plo, phi in [(0, .1), (.1, .3), (.3, .7), (.7, .9), (.9, 1.0)]:
            b = [r for r in recs if lo <= r["tau"] < hi and plo <= r["p_pm"] < phi]
            if len(b) < 40:
                continue
            w = sum(r["size"] for r in b)
            real = sum(r["size"] for r in b if r["up"]) / w
            mpm = sum(r["p_pm"] * r["size"] for r in b) / w
            mmd = sum(r["p_mod"] * r["size"] for r in b) / w
            print(f"{lab:>10} {plo:.1f}-{phi:<7.1f}{len(b):>7}{w:>12,.0f}"
                  f"{real:>10.3f}{real-mpm:>+9.3f}{real-mmd:>+10.3f}")

    # ---- threshold picked in-sample (older half), reported out-of-sample
    cut = len(recs) // 2
    train, test = recs[:cut], recs[cut:]
    print(f"\n{'='*78}\nRULE: bet when |model - PM| > threshold\n{'='*78}")
    print(f"{'thresh':>8} | {'TRAIN (older half)':^30} | {'TEST (newer half)':^30}")
    print(f"{'':>8} | {'n':>7}{'$staked':>12}{'ret/$':>10} | {'n':>7}{'$staked':>12}{'ret/$':>10}")
    best, best_ret = None, -9e9
    for th in (0.02, 0.05, 0.10, 0.15, 0.25):
        pt, st, nt = run_rule(train, th)
        pe, se, ne = run_rule(test, th)
        rt = pt / st if st > 0 else 0.0
        re_ = pe / se if se > 0 else 0.0
        print(f"{th:>8.2f} | {nt:>7}{st:>12,.0f}{rt:>+10.3f} | {ne:>7}{se:>12,.0f}{re_:>+10.3f}")
        if st > 1000 and rt > best_ret:
            best, best_ret = th, rt
    if best is None:
        print("no threshold with enough train volume")
        return

    # ---- permutation null on the OOS half
    pe, se, ne = run_rule(test, best)
    ends = sorted({r["end"] for r in test})
    truth = {e: next(r["up"] for r in test if r["end"] == e) for e in ends}
    rng = random.Random(SEED)
    null = []
    labels = [truth[e] for e in ends]
    for _ in range(200):
        rng.shuffle(labels)
        shuffled = dict(zip(ends, labels))
        p, s, _n = run_rule(test, best, shuffled)
        null.append(p / s if s > 0 else 0.0)
    null.sort()
    real_ret = pe / se if se > 0 else 0.0
    worse = sum(1 for v in null if v >= real_ret)
    print(f"\n{'='*78}\nPERMUTATION NULL  (threshold {best:.2f} chosen on train, tested on OOS half)\n{'='*78}")
    print(f"  real OOS return/$ : {real_ret:+.4f}   on ${se:,.0f} staked, {ne} bets")
    print(f"  shuffled-label null: median {statistics.median(null):+.4f}  "
          f"p90 {null[179]:+.4f}  p99 {null[197]:+.4f}")
    print(f"  p-value            : {(worse+1)/201:.3f}"
          f"   ({worse}/200 shuffles matched or beat the real number)")
    print("\n  p > 0.05 means random labels reproduce this result. no edge.")
    print("  and even a passing p is an UPPER BOUND -- it assumes we win every race.")


if __name__ == "__main__":
    main()
