"""
lucid_flex_25k.py — LucidFlex 25K: how to reach $1,400 AND bank 5 winning days.

THE PROBLEM, PRECISELY
----------------------
Two constraints must be satisfied at the same time, before the floor is hit:
    (a) balance +$1,400   -> so a 50%-capped request pays $700
    (b) 5 separate sessions each closing >= +$100

They are NOT independent, and that is the whole insight. Make $1,400 in one session and
you still owe 4 qualifying days, each of which now risks a $1,400 cushion for $100 of
progress. Make $280 on each of 5 sessions and the SAME dollars satisfy both.

RULES (lucidtrading.com; help centre returns 403, so eval numbers are cross-checked from
Igor's own figures + lunefi/traderspost reviews and they agree):
    eval target $1,250 | MLL $1,000 EOD trailing | 50% eval consistency
    P(pass) = 1000/(1000+1250) = 0.444   <- matches Igor's 44% exactly
    funded: no daily loss limit, no funded consistency, no buffer,
            withdraw <= 50% of profits, min $500, max $1,000, 90/10 split
    5 winning days at >= $100, resetting after each payout

    *** LUCID'S REAL EDGE: the drawdown updates on the END-OF-DAY CLOSE only, and the
    breach check does NOT run against intraday unrealized equity. A session that goes
    deep underwater and closes +$100 costs nothing and still counts as a winning day.
    That is strictly better than Tradeify, which kills you on the excursion. ***

UNRESOLVED: whether the funded drawdown LOCKS at start+$100. Help centre 403s. It flips
the optimal strategy, so both cases are solved below and the recommendation is the one
that is robust to not knowing.

Run: python3 scripts/lucid_flex_25k.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "toolkit"))

from propsim import EOD_TRAIL, INSTRUMENTS, FirmRules, MLLTracker, Policy  # noqa: E402

INST = dict(INSTRUMENTS["MNQ"])
TARGET_BAL = 1400.0        # balance needed so 50% of profit >= a $700 request
WIN_DAY = 100.0            # a session must close at least this much up to qualify
WIN_DAYS_NEEDED = 5
MLL = 1000.0
N = 40000


def funded_run(risk, daily_target, rng, lock_at=None, rr=1.0, max_trades_day=8,
               max_days=60):
    """One funded account. Returns (success, days_used, peak_balance).

    success = reached +$1,400 AND banked 5 qualifying days before hitting the floor.
    Breach is tested on the CLOSE only — Lucid's documented behaviour.
    """
    tr = MLLTracker(MLL, EOD_TRAIL, lock_at)
    eq = 0.0
    wins = 0
    p_win = 1.0 / (1.0 + rr)
    S, T = risk, risk * rr

    for day in range(1, max_days + 1):
        start = eq
        for _ in range(max_trades_day):
            if (eq - start) >= daily_target:
                break                                  # day's target hit, stop
            eq += (T if rng.random() < p_win else -S) - INST["cost_rt"] * max(
                1, int(risk / (INST["tick_value"] * 40)))
            # intraday breach is NOT checked: Lucid trails and enforces on the close
            if eq <= tr.threshold - 3000:
                break                                  # hopeless, stop burning
        tr.on_day_close(eq)
        if tr.breached(eq):
            return False, day, eq
        if (eq - start) >= WIN_DAY:
            wins += 1
        if eq >= TARGET_BAL and wins >= WIN_DAYS_NEEDED:
            return True, day, eq
    return False, max_days, eq


def sweep(lock_at, label):
    print(f"\n  {label}")
    print(f"  {'risk':>6} " + "".join(f"{f'${t:.0f}/day':>10}" for t in DAILY) +
          f"{'best':>10}")
    print("  " + "-" * 84)
    best = (-1, None)
    for risk in RISKS:
        row = []
        for dt in DAILY:
            rng = np.random.default_rng(7)
            ok = sum(funded_run(risk, dt, rng, lock_at)[0] for _ in range(N // 40))
            p = ok / (N // 40)
            row.append(p)
            if p > best[0]:
                best = (p, (risk, dt))
        print(f"  {risk:>6} " + "".join(f"{p:>10.3f}" for p in row) +
              f"{max(row):>10.3f}")
    print(f"\n  BEST: risk ${best[1][0]}, stop the day at +${best[1][1]:.0f}"
          f"  ->  P(reach $1,400 + 5 winning days) = {best[0]:.3f}")
    return best


RISKS = [400, 300, 250, 200, 150, 100, 75]
DAILY = [1400, 700, 460, 280, 200, 150]

if __name__ == "__main__":
    print(__doc__)
    print("=" * 90)
    print("  P(reach $1,400 AND 5 winning days before the floor)")
    print("  columns = daily stop-out target. $280/day x 5 days = $1,400 exactly.")
    print("=" * 90)
    b_lock = sweep(100.0, "IF the drawdown LOCKS at start + $100")
    b_nolock = sweep(None, "IF the drawdown NEVER locks (trails forever)")

    print("\n" + "=" * 90)
    print("  ROBUST CHOICE — best config that does not depend on the unknown lock rule")
    print("=" * 90)
    rows = []
    for risk in RISKS:
        for dt in DAILY:
            ps = []
            for lock in (100.0, None):
                rng = np.random.default_rng(7)
                ps.append(sum(funded_run(risk, dt, rng, lock)[0]
                              for _ in range(N // 40)) / (N // 40))
            rows.append((min(ps), ps[0], ps[1], risk, dt))
    rows.sort(reverse=True)
    print(f"\n  {'risk':>6} {'daily stop':>12} {'P(lock)':>9} {'P(no lock)':>11} "
          f"{'worst case':>12}")
    print("  " + "-" * 60)
    for w, a, b, risk, dt in rows[:6]:
        print(f"  {risk:>6} {f'+${dt:.0f}':>12} {a:>9.3f} {b:>11.3f} {w:>12.3f}")

    w, a, b, risk, dt = rows[0]
    print(f"""
  ANSWER: risk ${risk} per trade, stop the session at +${dt:.0f}, repeat.
  Worst case across both drawdown interpretations: {w:.1%}.

  Full-cycle EV, using Igor's ~$160 of eval fees per funded account:
      P(funded payout) = {w:.3f}
      payout           = $700 x 0.90 = $630
      EV per funded acct = {w:.3f} x 630 - 160 = ${w * 630 - 160:.0f}
""")
