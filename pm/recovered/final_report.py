"""Full 45-day verdict on the Polymarket hourly-crypto speed race.

Builds the record set ONCE (storing spot read at several deliberate staleness lags),
then runs every check off it:

  1. CALIBRATION      -- is the PM price honest about what happens?
  2. STALENESS SWEEP  -- does the edge decay with information age? (latency signature)
  3. CONCENTRATION    -- is the P&L carried by a handful of bets? (the thing the
                         permutation test is blind to, and what failed at 14 days)
  4. SIGNAL NULL      -- shuffle the SIGNAL, never the labels. See
                         feedback-permutation-null-must-shuffle-signal.

Model: P(Up) = Phi(d / (sigma*sqrt(tau))), zero fitted parameters.
sigma comes from the PREVIOUS full hour -- strictly prior, robust.

Everything here remains an UPPER BOUND: it assumes we win the race for prints that
actually happened, at their printed price. The tape has no aggressor side.
"""
import os
import sys
import math
import json
import random
import statistics
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze as A

LAGS = (1, 3, 10, 30)
THRESHOLDS = (0.05, 0.10, 0.20)
N_SHUF = 200
SEED = 20260830


def build():
    recs = []
    files = os.listdir(A.CACHE)
    for asset, symbol in A.ASSETS.items():
        pref = f"mkt_{asset}-up-or-down-"
        for fn in files:
            if not fn.startswith(pref):
                continue
            m = A.load(fn[:-5])
            if not m or m.get("vol", 0) < 500:
                continue
            end = int(dt.datetime.fromisoformat(
                m["endDate"].replace("Z", "+00:00")).timestamp())
            bn = A.load(f"bnc_{symbol}_{end}")
            sg = A.load(f"sigprev_{symbol}_{end}")
            if not bn or not bn.get("secs") or not sg or sg <= 0:
                continue
            if (bn["close"] >= bn["open"]) != m["up"]:
                continue
            tape = A.load("tape_" + m["cid"][:20])
            if not tape:
                continue
            secs = {int(k): v for k, v in bn["secs"].items()}
            op = bn["open"]
            for ts, p, sz in tape:
                tau = end - ts
                if not (1 <= tau <= 600) or sz <= 0 or not (0.0 < p < 1.0):
                    continue
                ds = {}
                for L in LAGS:
                    spot = None
                    for k in range(L, L + 3):
                        spot = secs.get(ts - k)
                        if spot:
                            break
                    if spot:
                        ds[L] = (spot - op) / op * 1e4
                if len(ds) < len(LAGS):
                    continue
                recs.append({"asset": asset, "end": end, "tau": tau, "p_pm": p,
                             "size": sz, "up": bool(m["up"]), "sigma": sg, "d": ds})
    recs.sort(key=lambda r: r["end"])
    return recs


def bets_for(recs, lag, thresh, dsub=None):
    """dsub: optional {index -> substituted d} for the signal null."""
    out = []
    for i, r in enumerate(recs):
        d = dsub[i] if dsub is not None else r["d"][lag]
        pm = A.norm_cdf(d / (r["sigma"] * math.sqrt(r["tau"])))
        e = pm - r["p_pm"]
        if abs(e) < thresh:
            continue
        up = e > 0
        px = r["p_pm"] if up else 1.0 - r["p_pm"]
        if px <= 0.001 or px >= 0.99:
            continue
        won = 1.0 if (r["up"] == up) else 0.0
        out.append((r["size"] * (won - px - A.fee(px)), r["size"] * px, r))
    return out


def stats(bets):
    if not bets:
        return None
    tot = sum(b[0] for b in bets)
    stk = sum(b[1] for b in bets)
    s = sorted(bets, key=lambda b: -b[0])
    days, hours = {}, {}
    for p, _s, r in bets:
        d = dt.datetime.utcfromtimestamp(r["end"]).date()
        days[d] = days.get(d, 0) + p
        hours[r["end"]] = hours.get(r["end"], 0) + p
    return {
        "n": len(bets), "pnl": tot, "staked": stk,
        "ret": tot / stk if stk else 0.0,
        "win": sum(1 for b in bets if b[0] > 0) / len(bets) * 100,
        "top20": sum(b[0] for b in s[:20]) / tot * 100 if tot else 0,
        "days": len(days), "days_pos": sum(1 for v in days.values() if v > 0),
        "med_day": statistics.median(days.values()),
        "hours": len(hours), "hours_pos": sum(1 for v in hours.values() if v > 0),
    }


def main():
    recs = build()
    mh = {(r["asset"], r["end"]) for r in recs}
    days = sorted({dt.datetime.utcfromtimestamp(r["end"]).date() for r in recs})
    print(f"{len(recs):,} trades | {len(mh)} market-hours | {len(days)} days "
          f"{days[0]} -> {days[-1]}")
    ups = {}
    for r in recs:
        ups[(r["asset"], r["end"])] = r["up"]
    nu = sum(1 for v in ups.values() if v)
    print(f"period base rate: {nu}/{len(ups)} up = {nu/len(ups)*100:.1f}%")

    print(f"\n{'='*90}\n1. CALIBRATION  (size-weighted, all trades in final 600s)\n{'='*90}")
    print(f"{'tau':>10}{'PM price':>12}{'n':>8}{'$ size':>13}{'realised':>10}{'PM gap':>9}")
    for lo, hi, lab in [(1, 15, "1-15s"), (15, 60, "15-60s"),
                        (60, 180, "60-180s"), (180, 600, "180-600s")]:
        for plo, phi in [(0, .1), (.1, .3), (.3, .7), (.7, .9), (.9, 1.0)]:
            b = [r for r in recs if lo <= r["tau"] < hi and plo <= r["p_pm"] < phi]
            if len(b) < 100:
                continue
            w = sum(r["size"] for r in b)
            real = sum(r["size"] for r in b if r["up"]) / w
            mpm = sum(r["p_pm"] * r["size"] for r in b) / w
            print(f"{lab:>10}{f'{plo:.1f}-{phi:.1f}':>12}{len(b):>8}{w:>13,.0f}"
                  f"{real:>10.3f}{real-mpm:>+9.3f}")

    print(f"\n{'='*90}\n2. STALENESS SWEEP + 3. CONCENTRATION\n{'='*90}")
    print(f"{'k':>4}{'thr':>6}{'bets':>8}{'$staked':>11}{'ret/$':>9}{'pnl':>11}"
          f"{'win%':>7}{'top20':>8}{'days+':>9}{'med/day':>10}{'hours+':>10}")
    for lag in LAGS:
        for th in THRESHOLDS:
            st = stats(bets_for(recs, lag, th))
            if not st or st["n"] < 50:
                continue
            print(f"{lag:>4}{th:>6.2f}{st['n']:>8}{st['staked']:>11,.0f}"
                  f"{st['ret']:>+9.3f}{st['pnl']:>+11,.0f}{st['win']:>7.1f}"
                  f"{st['top20']:>7.0f}%{f'{st[chr(100)+chr(97)+chr(121)+chr(115)}+chr(95)+chr(112)+chr(111)+chr(115)]}' if False else f'{st[\"days_pos\"]}/{st[\"days\"]}':>9}"
                  f"{st['med_day']:>+10,.0f}"
                  f"{f'{st[\"hours_pos\"]}/{st[\"hours\"]}':>10}")

    print(f"\n{'='*90}\n4. SIGNAL NULL  (shuffle d within asset x tau-bucket; labels untouched)\n{'='*90}")
    groups = {}
    for i, r in enumerate(recs):
        tb = 0 if r["tau"] < 15 else 1 if r["tau"] < 60 else 2 if r["tau"] < 180 else 3
        groups.setdefault((r["asset"], tb), []).append(i)
    rng = random.Random(SEED)
    print(f"{'k':>4}{'thr':>6}{'REAL ret/$':>12}{'null med':>10}{'null p90':>10}"
          f"{'null p99':>10}{'p-value':>9}")
    for lag in (1, 10):
        for th in THRESHOLDS:
            real_bets = bets_for(recs, lag, th)
            if len(real_bets) < 50:
                continue
            rs = sum(b[1] for b in real_bets)
            real = sum(b[0] for b in real_bets) / rs if rs else 0.0
            null = []
            for _ in range(N_SHUF):
                dsub = {}
                for _k, idxs in groups.items():
                    don = idxs[:]
                    rng.shuffle(don)
                    for t, s_ in zip(idxs, don):
                        dsub[t] = recs[s_]["d"][lag]
                nb = bets_for(recs, lag, th, dsub)
                ns = sum(b[1] for b in nb)
                null.append(sum(b[0] for b in nb) / ns if ns else 0.0)
            null.sort()
            beat = sum(1 for v in null if v >= real)
            print(f"{lag:>4}{th:>6.2f}{real:>+12.3f}{statistics.median(null):>+10.3f}"
                  f"{null[int(.90*N_SHUF)]:>+10.3f}{null[int(.99*N_SHUF)]:>+10.3f}"
                  f"{(beat+1)/(N_SHUF+1):>9.3f}")

    print("\nUPPER BOUND: assumes we win the race for prints that actually happened.")


if __name__ == "__main__":
    main()
