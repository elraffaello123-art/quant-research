"""The decisive test: does Binance spot know anything the Polymarket price doesn't?

WHY A NEW NULL
--------------
Shuffling OUTCOMES is invalid here. Prices and outcomes are entangled by the book's
own calibration -- a 0.05 bet normally wins 5% of the time, but under shuffled labels
it wins 50%, which manufactures a fake +100% return. That null answers no question.

The right null scrambles the SIGNAL and leaves everything else exactly as it was:
replace this hour's spot-distance `d` with `d` drawn from a DIFFERENT hour (same asset,
same time-to-close bucket, so the scale of the statistic is preserved). Outcomes, PM
prices, sizes, sigmas and bet counts all stay put.

That asks precisely the question we care about:
    beyond what the PM price already tells us, does knowing Binance spot add anything?

If the real rule sits inside the shuffled-signal distribution, spot adds nothing and
the speed thesis is dead on this market.
"""
import sys
import os
import math
import random
import statistics

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze as A

SEED = 20260830
N_SHUF = 200
THRESHOLDS = (0.02, 0.05, 0.10, 0.15)


def tau_bucket(tau):
    return 0 if tau < 15 else 1 if tau < 60 else 2 if tau < 180 else 3


def pnl_for(recs, thresh, dmap=None):
    """dmap: optional {index -> substituted d} for the null."""
    pnl = staked = 0.0
    n = 0
    for i, r in enumerate(recs):
        d = dmap[i] if dmap is not None else r["d"]
        p_mod = A.norm_cdf(d / (r["sigma"] * math.sqrt(r["tau"])))
        edge = p_mod - r["p_pm"]
        if abs(edge) < thresh:
            continue
        buy_up = edge > 0
        px = r["p_pm"] if buy_up else 1.0 - r["p_pm"]
        if px <= 0.001 or px >= 0.99:
            continue
        won = 1.0 if (r["up"] == buy_up) else 0.0
        pnl += r["size"] * (won - px - A.fee(px))
        staked += r["size"] * px
        n += 1
    return pnl, staked, n


def main():
    recs = A.build()
    print(f"{len(recs):,} trades across {len({(r['asset'], r['end']) for r in recs})} market-hours\n")

    # group indices by (asset, tau bucket) so the shuffle preserves scale
    groups = {}
    for i, r in enumerate(recs):
        groups.setdefault((r["asset"], tau_bucket(r["tau"])), []).append(i)

    rng = random.Random(SEED)
    print(f"{'thresh':>7}{'n bets':>8}{'$staked':>11}{'REAL ret/$':>12}"
          f"{'null med':>10}{'null p90':>10}{'null p99':>10}{'p-value':>9}")
    for th in THRESHOLDS:
        p, s, n = pnl_for(recs, th)
        if s <= 0 or n < 30:
            continue
        real = p / s
        null = []
        for _ in range(N_SHUF):
            dmap = {}
            for _key, idxs in groups.items():
                donors = idxs[:]
                rng.shuffle(donors)
                for tgt, src in zip(idxs, donors):
                    dmap[tgt] = recs[src]["d"]
            pn, sn, _ = pnl_for(recs, th, dmap)
            null.append(pn / sn if sn > 0 else 0.0)
        null.sort()
        beat = sum(1 for v in null if v >= real)
        print(f"{th:>7.2f}{n:>8}{s:>11,.0f}{real:>+12.3f}"
              f"{statistics.median(null):>+10.3f}{null[int(.90*N_SHUF)]:>+10.3f}"
              f"{null[int(.99*N_SHUF)]:>+10.3f}{(beat+1)/(N_SHUF+1):>9.3f}")

    print("\np <= 0.05  -> spot carries information the PM price does not.")
    print("p >  0.05  -> the rule is just riding the book's own calibration. dead.")
    print("either way this is an UPPER BOUND: it assumes we win the race for real prints.")


if __name__ == "__main__":
    main()
