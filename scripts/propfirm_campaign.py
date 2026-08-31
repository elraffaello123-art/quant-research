"""
propfirm_campaign.py — EV with RESET economics. Supersedes the fee handling in
`propfirm_mc.py`, which priced every attempt at the purchase price and was wrong.

THE CORRECTION
--------------
A failed evaluation is RESET, not re-bought. So a campaign is:

    pay fee_eval once, then fee_reset per failure, until one passes

    E[cost per pass] = fee_eval + (1/P - 1) x fee_reset
    EV per attempt   = P x ( E[paid | pass] - E[cost per pass] )

Charging fee_eval on every attempt overstates campaign cost badly. On Tradeify Select
the reset is $95 against a $165 purchase — a 42% discount — and that single correction
moves the account from -$40/attempt to +$17/attempt. Firms differ enormously here:
MFFU does not discount resets at all, Tradeify discounts them heavily. It reorders
the table.

Both readings of Tradeify's self-contradictory drawdown rule are reported, because the
answer depends on it and the firm's own documentation does not resolve it.

Run: python3 scripts/propfirm_campaign.py
"""
import os
import sys
from dataclasses import replace

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "toolkit"))
sys.path.insert(0, HERE)

from propfirm_accounts import ACCOUNTS                      # noqa: E402
from propsim import INSTRUMENTS, Policy, simulate_account   # noqa: E402

STOP_TICKS = 40
N = 12000


def max_risk(a, instrument="MNQ"):
    minis = a.max_contracts
    limit = minis * 10 if instrument in ("MNQ", "MES") else minis
    return limit * INSTRUMENTS[instrument]["tick_value"] * STOP_TICKS


def campaign(a, unreal=True, n=N, seed=11):
    """EV per attempt under reset economics, with a bootstrap CI."""
    rules = replace(a, breach_on_unrealized=unreal)
    er = max_risk(a)
    pol = Policy(rr=2.0, risk_per_trade=min(er, 600), stop_ticks=STOP_TICKS,
                 trades_per_day=1,
                 funded_risk_per_trade=min(er, 1000), funded_trades_per_day=1,
                 max_days=90, eval_days_cap=15)
    rng = np.random.default_rng(seed)
    res = [simulate_account(rules, pol, "MNQ", rng) for _ in range(n)]
    paid = np.array([r.paid for r in res])
    ps = np.array([r.passed for r in res])
    days = np.array([r.days for r in res])

    reset = a.fee_reset if a.fee_reset is not None else a.fee_eval
    P = ps.mean()
    if P == 0:
        return dict(P=0.0, ev=-a.fee_eval, lo=np.nan, hi=np.nan, epp=0.0,
                    cost=a.fee_eval, days=days.mean(), reset=reset,
                    reset_known=a.fee_reset is not None)
    epp = paid[ps].mean()
    cost = a.fee_eval + (1.0 / P - 1.0) * reset
    ev = P * (epp - cost)

    rg = np.random.default_rng(3)
    bs = []
    for _ in range(300):
        i = rg.integers(0, n, n)
        p_ = ps[i].mean()
        if p_ <= 0:
            continue
        e_ = paid[i][ps[i]].mean()
        bs.append(p_ * (e_ - (a.fee_eval + (1 / p_ - 1) * reset)))
    lo, hi = np.percentile(bs, [2.5, 97.5]) if bs else (np.nan, np.nan)
    return dict(P=P, ev=ev, lo=lo, hi=hi, epp=epp, cost=cost, days=days.mean(),
                reset=reset, reset_known=a.fee_reset is not None)


def main():
    print(__doc__)
    for label, unreal in [("MLL breach on UNREALIZED equity (harsh reading)", True),
                          ("MLL breach on CLOSED balance only (lenient reading)", False)]:
        print("=" * 96)
        print(f"  {label}")
        print("=" * 96)
        print(f"  {'account':<26} {'fee':>7} {'reset':>7} {'P(pass)':>8} "
              f"{'$/pass':>8} {'cost':>8} {'EV/att':>8} {'95% CI':>16} {'':>6}")
        print("  " + "-" * 92)
        rows = []
        for a in ACCOUNTS:
            r = campaign(a, unreal=unreal)
            rows.append((a, r))
        for a, r in sorted(rows, key=lambda x: -x[1]["ev"]):
            flag = "" if r["reset_known"] else "  (reset fee NOT FOUND -> used fee_eval)"
            v = "+EV" if r["lo"] > 0 else ("-EV" if r["hi"] < 0 else "NOISE")
            print(f"  {a.name:<26} {a.fee_eval:>7.0f} {r['reset']:>7.0f} "
                  f"{r['P']:>8.3f} {r['epp']:>8.0f} {r['cost']:>8.0f} "
                  f"{r['ev']:>8.1f} [{r['lo']:>6.0f},{r['hi']:>6.0f}] {v:>6}{flag}")
        print()

    print("=" * 96)
    print("  WHAT CHANGED, AND WHAT DID NOT")
    print("=" * 96)
    print("""
  CHANGED: reset pricing. Failures are cheap on firms that discount resets, so a
  campaign of many cheap attempts at a ~20% pass rate clears the cost of one pass.
  This is the mechanic that makes the structure work and it was missing before.

  UNCHANGED: the funded-stage ceiling. E[lifetime extraction] is still bounded by the
  distance to the MLL, so E[paid|pass] does not move. Resets cut the COST of reaching
  a funded account; they do nothing for what a funded account is worth.

  STILL OUTSTANDING, and it dominates everything above:
    - the discretionary-denial clauses. Alpha and FundedNext ban "account rolling" —
      buying/resetting repeatedly to pass on probability — BY NAME. A reset campaign
      is the literal definition of what they prohibit. Tradeify has no such clause,
      which is now the main reason to prefer it.
    - Tradeify caps resets at 10 per 30 days and evals at 15 per 30 days, so campaign
      throughput is capped regardless of EV.
    - funded-stage contract scaling (start at half size) is still not modelled and
      still cuts the other way.
""")


if __name__ == "__main__":
    main()
