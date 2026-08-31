"""
propfirm_minimal_trades.py — the MINIMUM-TRADE policy. Igor's, 2026-08-20.

    python3 scripts/propfirm_minimal_trades.py

WHY THIS EXISTS
---------------
`propfirm_daily_mc.py` swept funded risk up to $400 and found every account -EV. That sweep
could not see the policy that actually matters, because the optimum is not in the grid:

    EVAL    one trade per day, sized so exactly N wins clear the target, where N is the
            smallest number the eval CONSISTENCY rule permits. Nothing else is traded.
    FUNDED  ONE trade. Risk essentially the whole MLL. Take the payout. Stop.

Minimum trades everywhere. The reasoning is the martingale: a zero-edge account dies with
probability 1, so every extra trade is another chance to die and another round-turn of cost
drag, while adding nothing to expectation. The only reason to trade at all is to satisfy a
rule. So satisfy it in the fewest possible trades and leave.

THE CONSISTENCY RULE SETS THE NUMBER OF EVAL WINS
-------------------------------------------------
A c% consistency rule means no single day may exceed c% of total profit. Passing on N equal
winning days makes the best day exactly 1/N of the profit, so the rule is satisfied iff
1/N <= c, i.e.  N = ceil(1/c).

    50% -> 2 wins of target/2      (MFFU Rapid, LucidDaily, TPT)
    40% -> 3 wins of target/3      (Tradeify Select)
    30% -> 4 wins of target/4      (MFFU Rapid EOD)

Note this lands exactly on each firm's minimum-trading-days requirement. That is not a
coincidence — the two rules are the same constraint written twice.

WHY THE FUNDED TRADE MUST OVERSHOOT THE BUFFER
----------------------------------------------
The buffer is must-REMAIN (Igor): you must be above it to request AND still above it after.
So a funded trade that lands exactly on the buffer withdraws nothing. To bank X you must
target buffer + X. With risk R and target buffer+X, a driftless walk gives
P = R / (R + buffer + X), and the payout is X * split. There is a real optimum in X:
raise it and you bank more but hit it less often. That trade-off is swept below.

CONTRACT FEASIBILITY: propsim uses `contracts` only to compute cost, so `stop_ticks` is set
per cell to keep the contract count inside each firm's limit. Cells that cannot be traded
inside the limit are marked INFEASIBLE and excluded, not silently priced.
"""

import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "toolkit"))
sys.path.insert(0, HERE)

from dataclasses import replace                       # noqa: E402
from propfirm_daily_accounts import DAILY_ACCOUNTS    # noqa: E402
from propsim import INSTRUMENTS, Policy, simulate_account  # noqa: E402

INST = "MNQ"
N = 20000
# How far ABOVE the buffer the single funded trade aims. This is the only free knob.
OVERSHOOT = [500, 750, 1000, 1500, 2000, 3000]
FEE_DISCOUNTS = [0.0, 0.30, 0.40, 0.50]


def micro_limit(a):
    """Contract ceiling in MNQ micros (firms quote minis; 1 mini = 10 micros)."""
    return a.max_contracts * 10


def feasible_stop(a, risk):
    """Smallest stop width (ticks) that keeps `risk` inside the contract limit.

    contracts = risk / (tick_value * stop_ticks) must be <= the micro limit.
    """
    tv = INSTRUMENTS[INST]["tick_value"]
    need = risk / (tv * micro_limit(a))
    return int(math.ceil(need))


def eval_wins(a):
    """N equal winning days that satisfy the eval consistency rule, and the min-days rule."""
    c = a.eval_consistency_pct
    n_consist = 1 if c is None else int(math.ceil(1.0 / c))
    return max(n_consist, a.eval_min_days, 1)


def run(a, overshoot, n=N, seed=0, p_denied=0.0, fee_mult=1.0):
    """One cell of the minimum-trade policy."""
    nwin = eval_wins(a)
    eval_risk = a.eval_target / nwin           # exactly nwin wins clears the target
    buffer = max(a.payout_keep_buffer, a.payout_min_profit)
    funded_risk = a.funded_mll - 100.0         # risk it all, short of the floor
    funded_rr = (buffer + overshoot) / funded_risk

    stop = max(feasible_stop(a, eval_risk), feasible_stop(a, funded_risk))
    if stop > 400:                             # absurd bracket -> not tradeable
        return None

    rules = replace(a, p_payout_denied=p_denied,
                    fee_eval=a.fee_eval * fee_mult,
                    fee_reset=(a.fee_reset or a.fee_eval) * fee_mult)
    pol = Policy(rr=1.0, risk_per_trade=eval_risk,
                 funded_risk_per_trade=funded_risk,
                 stop_ticks=stop,
                 trades_per_day=1, funded_trades_per_day=1,
                 max_days=30, eval_days_cap=30,
                 first_payout_at=0.0, keep_buffer=0.0,
                 coast_risk=20.0)
    # The funded stage wants a different reward:risk than the eval. propsim carries one
    # `rr`, so the funded leg is priced by re-running with the funded rr and splicing:
    # P(pass) comes from the eval-rr run, the funded outcome from the funded-rr run.
    rng = np.random.default_rng(seed)
    passed = np.zeros(n, bool)
    for k in range(n):
        r = simulate_account(rules, pol, INST, rng)
        passed[k] = r.passed
    p_pass = passed.mean()

    # `simulate_account` restarts equity at 0 for the funded stage, so a trivially-passed
    # eval gives a clean funded-only sample -- but ONLY conditional on reaching it. Some
    # fake evals still die, and averaging their 0s into E[paid] would bias it downward.
    pol_f = replace(pol, rr=funded_rr)
    rng2 = np.random.default_rng(seed + 1)
    paid, got_there = [], 0
    for k in range(n):
        r = simulate_account(replace(rules, eval_target=0.01, eval_min_days=0,
                                     eval_consistency_pct=None),
                             pol_f, INST, rng2)
        if r.passed:
            paid.append(r.paid)
            got_there += 1
    e_paid_given_pass = float(np.mean(paid)) if got_there else 0.0

    # One attempt = one fee. The eval is 2-6 sessions and the funded leg is one trade, so
    # a monthly plan is billed once; a failed attempt is re-bought at fee_reset, which is
    # what the next attempt's EV is charged. Not multiplied.
    fee = rules.fee_eval
    ev = -fee - a.fee_activation * p_pass + p_pass * e_paid_given_pass
    return dict(ev=ev, p_pass=p_pass, e_paid=e_paid_given_pass, fee=fee,
                nwin=nwin, eval_risk=eval_risk, funded_risk=funded_risk,
                funded_rr=funded_rr, stop=stop, overshoot=overshoot)


def main():
    print("=" * 104)
    print("  MINIMUM-TRADE POLICY — pass in N wins, then ONE funded trade, then withdraw")
    print("=" * 104)
    print(f"\n  {'account':<28} {'wins':>5} {'evalRisk':>9} {'fundRisk':>9} "
          f"{'buffer':>7} {'stop':>5}")
    print("  " + "-" * 100)
    for a in DAILY_ACCOUNTS:
        nwin = eval_wins(a)
        er = a.eval_target / nwin
        fr = a.funded_mll - 100.0
        buf = max(a.payout_keep_buffer, a.payout_min_profit)
        print(f"  {a.name:<28} {nwin:>5d} {er:>9.0f} {fr:>9.0f} {buf:>7.0f} "
              f"{max(feasible_stop(a,er), feasible_stop(a,fr)):>5d}")

    print("\n" + "=" * 104)
    print("  EV vs how far the single funded trade overshoots the buffer  (list price)")
    print("=" * 104)
    print(f"\n  {'account':<28} " + "".join(f"{f'+${o}':>9}" for o in OVERSHOOT))
    print("  " + "-" * 100)
    best = {}
    for a in DAILY_ACCOUNTS:
        row = []
        for o in OVERSHOOT:
            r = run(a, o)
            row.append(r)
            if r and (a.name not in best or r["ev"] > best[a.name]["ev"]):
                best[a.name] = r
        print(f"  {a.name:<28} " +
              "".join(f"{(r['ev'] if r else float('nan')):>9.0f}" for r in row))

    print("\n" + "=" * 104)
    print("  BEST CELL PER ACCOUNT, with the fee discounts these firms actually run")
    print("=" * 104)
    print(f"\n  {'account':<28} {'over':>6} {'P(pass)':>8} {'E[paid|pass]':>13} "
          f"{'list':>8} {'-30%':>8} {'-40%':>8} {'-50%':>8}")
    print("  " + "-" * 100)
    for a in DAILY_ACCOUNTS:
        b = best.get(a.name)
        if b is None:
            print(f"  {a.name:<28}   INFEASIBLE")
            continue
        evs = [run(a, b["overshoot"], fee_mult=1 - d)["ev"] for d in FEE_DISCOUNTS]
        print(f"  {a.name:<28} {b['overshoot']:>6.0f} {b['p_pass']:>8.3f} "
              f"{b['e_paid']:>13.0f} " + "".join(f"{e:>8.0f}" for e in evs))

    print("\n" + "=" * 104)
    print("  DISCRETIONARY PAYOUT DENIAL on the best cell, at 40% off")
    print("=" * 104)
    print(f"\n  {'account':<28} {'p=0':>9} {'p=0.10':>9} {'p=0.25':>9} {'p=0.50':>9}")
    print("  " + "-" * 100)
    for a in DAILY_ACCOUNTS:
        b = best.get(a.name)
        if b is None:
            continue
        evs = [run(a, b["overshoot"], p_denied=pd_, fee_mult=0.60)["ev"]
               for pd_ in (0.0, 0.10, 0.25, 0.50)]
        print(f"  {a.name:<28} " + "".join(f"{e:>9.0f}" for e in evs))


if __name__ == "__main__":
    main()
