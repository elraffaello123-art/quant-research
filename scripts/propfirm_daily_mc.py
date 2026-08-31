"""
propfirm_daily_mc.py — EV of a ZERO-EDGE coinflip on the daily-payout accounts.

    python3 scripts/propfirm_daily_mc.py

Reuses the validated engine: `toolkit/propsim.py` + `run_cell` from `propfirm_mc.py`.
Run `python3 toolkit/propsim_tests.py` first — 14 checks, all must pass.

Answers, in order:
  1. Closed-form upper bound per account (geometry and fee only).
  2. Best-policy simulated EV, sweeping funded risk x trades-per-day.
  3. INTRADAY vs EOD, held all else equal (MFFU Rapid vs Rapid EOD; LucidDaily toggle).
  4. The two high-leverage uncertain rules, swept rather than assumed:
       - MFFU buffer semantics (must-reach vs must-remain)
       - TPT's 50% split inside the buffer zone under 60 trading days
  5. Discretionary payout denial.
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "toolkit"))
sys.path.insert(0, HERE)

from dataclasses import replace                       # noqa: E402
from propfirm_daily_accounts import DAILY_ACCOUNTS    # noqa: E402
from propfirm_mc import run_cell, closed_form, max_risk  # noqa: E402

INST = "MNQ"
RR = 1.0
N = 8000
N_SWEEP = 1500
FUNDED_GRID = [400, 250, 150, 100, 50, 25]
TPD_GRID = [1, 2, 4]
# Eval risk MUST be swept, not maxed. In a bare eval, size does not change P(pass), so
# maxing it is optimal for speed -- but an eval CONSISTENCY rule breaks that: if a single
# day's profit can exceed pct * target, the pass is blocked and coasting at token size
# cannot dilute it, because equity is pinned near the target. Maxing eval risk on MFFU
# Rapid EOD (30%) and TPT (50%) drives P(pass) to exactly ZERO -- a policy failure that
# looks like a dead account. Sweep it.
EVAL_GRID = [1000, 600, 400, 250, 150, 100]


def best_policy(a, p_denied=0.0, n=N_SWEEP, n_final=N):
    """Sweep eval risk x funded risk x trades-per-day; re-run the winner at full n."""
    ceiling = max_risk(a, INST)
    evals = sorted({min(e, ceiling) for e in EVAL_GRID}, reverse=True)
    best = None
    for er in evals:
        for fr in FUNDED_GRID:
            for tpd in TPD_GRID:
                r = run_cell(a, INST, RR, er, n=n, p_denied=p_denied,
                             funded_risk=fr, funded_tpd=tpd)
                if best is None or r["ev"] > best[0]["ev"]:
                    best = (r, fr, tpd, er)
    _, fr, tpd, er = best
    r = run_cell(a, INST, RR, er, n=n_final, p_denied=p_denied,
                 funded_risk=fr, funded_tpd=tpd)
    return r, fr, tpd, er


def main():
    print("=" * 100)
    print("  DAILY-PAYOUT ACCOUNTS — zero-edge coinflip, $50K, MNQ, 1:1")
    print("=" * 100)

    print(f"\n  {'account':<28} {'fee':>7} {'target':>7} {'MLL':>6} {'evalDD':>9} "
          f"{'fundDD':>9} {'split':>6} {'P(pass)':>8} {'closedEV':>9}")
    print("  " + "-" * 96)
    for a in DAILY_ACCOUNTS:
        cf, p = closed_form(a)
        print(f"  {a.name:<28} {a.fee_eval:>7.0f} {a.eval_target:>7.0f} {a.eval_mll:>6.0f} "
              f"{a.eval_mll_type[:9]:>9} {a.funded_mll_type[:9]:>9} {a.profit_split:>6.2f} "
              f"{p:>8.3f} {cf:>9.0f}")
    print("\n  closedEV is an UPPER BOUND: it assumes you extract the full martingale")
    print("  value of the funded account, which the payout rules never allow.")

    print("\n" + "=" * 100)
    print("  SIMULATED EV — best funded policy, every rule friction on")
    print("=" * 100)
    print(f"\n  {'account':<28} {'EV':>8} {'95% CI':>18} {'P(pass)':>8} {'E[paid]':>8} "
          f"{'fee':>7} {'trapped':>8} {'evalR':>6} {'fundR':>6} {'t/day':>6}")
    print("  " + "-" * 96)
    results = {}
    for a in DAILY_ACCOUNTS:
        r, fr, tpd, er = best_policy(a)
        results[a.name] = (r, fr, tpd, er)
        print(f"  {a.name:<28} {r['ev']:>8.0f} "
              f"[{r['ev_lo']:>7.0f},{r['ev_hi']:>7.0f}] {r['p_pass']:>8.3f} "
              f"{r['e_paid']:>8.0f} {r['fee']:>7.0f} {r['p_trapped']:>8.1%} "
              f"{er:>6.0f} {fr:>6.0f} {tpd:>6d}")
    print("\n  'trapped' = passed the eval but never got a single payout out.")

    print("\n" + "=" * 100)
    print("  INTRADAY vs EOD DRAWDOWN — the controlled comparisons")
    print("=" * 100)
    pairs = [("MFFU Rapid 50K (intraday)", "MFFU Rapid EOD 50K",
              "funded trail; EOD costs 2 extra min-days, 30% vs 50% consistency, 3 vs 5 minis"),
             ("LucidDaily 50K int+DLL", "LucidDaily 50K EOD+DLL",
              "EVAL trail only (funded is intraday either way); EOD costs $17.40 more")]
    for lo_name, hi_name, note in pairs:
        a_lo = results[lo_name][0]
        a_hi = results[hi_name][0]
        print(f"\n  {note}")
        print(f"    {lo_name:<30} EV {a_lo['ev']:>7.0f}   P(pass) {a_lo['p_pass']:.3f}")
        print(f"    {hi_name:<30} EV {a_hi['ev']:>7.0f}   P(pass) {a_hi['p_pass']:.3f}")
        print(f"    -> EOD is worth {a_hi['ev'] - a_lo['ev']:+.0f} per account")

    print("\n" + "=" * 100)
    print("  THE TWO HIGH-LEVERAGE UNCERTAIN RULES, SWEPT NOT ASSUMED")
    print("=" * 100)

    print("\n  (a) MFFU buffer: must-REACH $2,100 (modelled) vs must-REMAIN $2,100")
    for nm in ("MFFU Rapid 50K (intraday)", "MFFU Rapid EOD 50K"):
        a = next(x for x in DAILY_ACCOUNTS if x.name == nm)
        r_reach = results[nm][0]
        a_remain = replace(a, payout_keep_buffer=2_100.0)
        r_remain = best_policy(a_remain)[0]
        print(f"    {nm:<30} reach {r_reach['ev']:>7.0f}   remain {r_remain['ev']:>7.0f}   "
              f"delta {r_remain['ev']-r_reach['ev']:+.0f}")

    print("\n  (b) TPT split inside the buffer zone: 80% (modelled) vs 50% (<60 trading days)")
    a = next(x for x in DAILY_ACCOUNTS if x.name.startswith("TakeProfit"))
    r80 = results[a.name][0]
    r50 = best_policy(replace(a, profit_split=0.50))[0]
    print(f"    {a.name:<30} 80% {r80['ev']:>7.0f}   50% {r50['ev']:>7.0f}   "
          f"delta {r50['ev']-r80['ev']:+.0f}")

    print("\n" + "=" * 100)
    print("  FEE DISCOUNTS — these firms run 30-50% off codes near-permanently (Igor)")
    print("=" * 100)
    print("\n  The fee is the option premium. It is the ONLY term in the whole structure")
    print("  the trader can negotiate, so it is where any +EV has to come from.\n")
    print(f"  {'account':<28} {'list':>8} {'-30%':>8} {'-40%':>8} {'-50%':>8} "
          f"{'breakeven':>10}")
    print("  " + "-" * 96)
    for a in DAILY_ACCOUNTS:
        _, fr, tpd, er = results[a.name]
        row = {}
        for d in (0.0, 0.30, 0.40, 0.50):
            disc = replace(a, fee_eval=a.fee_eval * (1 - d),
                           fee_reset=(a.fee_reset or a.fee_eval) * (1 - d))
            row[d] = run_cell(disc, INST, RR, er, n=N, p_denied=0.0,
                              funded_risk=fr, funded_tpd=tpd)["ev"]
        # fee that would make EV exactly zero: EV(list) + fee_paid = gross payout
        r0 = results[a.name][0]
        breakeven = r0["fee"] + r0["ev"]        # = E[paid]; fee must fall to this
        print(f"  {a.name:<28} {row[0.0]:>8.0f} {row[0.30]:>8.0f} {row[0.40]:>8.0f} "
              f"{row[0.50]:>8.0f} {breakeven:>10.0f}")
    print("\n  'breakeven' = the total fee at which EV hits zero, i.e. E[paid].")
    print("  Compare it to the 'fee' column above: if breakeven < 50% of the fee")
    print("  actually charged, no realistic discount rescues the account.")

    print("\n" + "=" * 100)
    print("  DISCRETIONARY PAYOUT DENIAL")
    print("=" * 100)
    print(f"\n  {'account':<28} {'p=0':>9} {'p=0.10':>9} {'p=0.25':>9} {'p=0.50':>9}")
    print("  " + "-" * 96)
    for a in DAILY_ACCOUNTS:
        row = []
        for pd_ in (0.0, 0.10, 0.25, 0.50):
            if pd_ == 0.0:
                row.append(results[a.name][0]["ev"])
            else:
                _, fr, tpd, er = results[a.name]
                row.append(run_cell(a, INST, RR, er, n=N, p_denied=pd_,
                                    funded_risk=fr, funded_tpd=tpd)["ev"])
        print(f"  {a.name:<28} " + "".join(f"{v:>9.0f}" for v in row))

    print("\n" + "=" * 100)
    print("  UNVERIFIED — every number below is NOT confirmed")
    print("=" * 100)
    for a in DAILY_ACCOUNTS:
        if a.unverified:
            print(f"\n  {a.name}   [{a.source}]")
            for u in a.unverified:
                print(f"      - {u}")


if __name__ == "__main__":
    main()
