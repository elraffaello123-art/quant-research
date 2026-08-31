"""
propfirm_mc.py — total EV of running a zero-edge coinflip across the researched firms.

    python3 scripts/propfirm_mc.py

Reports, per account:
  * the CLOSED FORM upper bound, so you can see what the geometry alone says
  * the simulated EV per cycle and per week, with every rule friction switched on
  * the gap between them, which IS the cost of the payout rules
  * sensitivity to discretionary payout denial

Run `python3 toolkit/propsim_tests.py` first. If those don't all pass, nothing here
means anything.
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "toolkit"))
sys.path.insert(0, HERE)

from propfirm_accounts import ACCOUNTS          # noqa: E402
from propsim import INSTRUMENTS, Policy, simulate_account  # noqa: E402

STOP_TICKS = 40
N = 6000
# Funded-stage risk grid. Goes down to $25 because the binding constraint there is
# surviving enough sessions to bank the benchmark days, not reaching any target.
FUNDED_GRID = [600, 400, 250, 150, 100, 50, 25]
# Trades per session in the funded stage. 1 is included because it maximises the
# chance a session closes above the benchmark bar per unit of variance risked.
TPD_GRID = [1, 2, 4, 8]


def closed_form(a, split_on_mll=True):
    """EV if the ONLY things that existed were the two barriers and the fee.

    EV = -fee + P(pass) * split * (funded distance to MLL)
    with P(pass) = D/(D+T).

    This is an upper bound. It assumes you always extract the full martingale value
    of the funded account, which the payout rules will not let you do.
    """
    p = a.eval_mll / (a.eval_mll + a.eval_target)
    extract = a.funded_mll * a.profit_split
    return -a.fee_eval - a.fee_activation * p + p * extract, p


def max_risk(a, instrument):
    """Largest per-trade risk the contract limit allows, at a 40-tick stop.

    `max_contracts` is stored in MINIS, which is how every firm publishes it. The
    micro allowance is 10x the mini allowance at every firm researched, and a micro
    is 1/10 the size — so the DOLLAR cap is identical either way. Forgetting the 10x
    here caps MNQ at a tenth of the real limit and makes every account look unpassable.
    """
    minis = a.max_contracts
    limit = minis * 10 if instrument in ("MNQ", "MES") else minis
    return limit * INSTRUMENTS[instrument]["tick_value"] * STOP_TICKS


def run_cell(a, instrument, rr, risk, n=N, seed=0, p_denied=0.0, funded_risk=None,
             funded_tpd=None):
    from dataclasses import replace
    rules = replace(a, p_payout_denied=p_denied)
    pol = Policy(rr=rr, risk_per_trade=risk, funded_risk_per_trade=funded_risk,
                 stop_ticks=STOP_TICKS,
                 trades_per_day=4, funded_trades_per_day=funded_tpd,
                 max_days=60, eval_days_cap=15,
                 first_payout_at=0.0, keep_buffer=0.0)
    rng = np.random.default_rng(seed)

    paid = np.zeros(n); passed = np.zeros(n, bool)
    days = np.zeros(n); drag = np.zeros(n)
    causes = {"mll": 0, "timeout": 0, "daily_loss": 0}
    trapped = 0          # passed the eval but never got a single payout out
    for k in range(n):
        r = simulate_account(rules, pol, instrument, rng)
        paid[k], passed[k], days[k], drag[k] = r.paid, r.passed, r.days, r.cost_drag
        if not r.passed and r.cause in causes:
            causes[r.cause] += 1
        if r.passed and r.paid == 0.0:
            trapped += 1

    # Subscription firms (Alpha, MFFU Pro) bill EVERY month the account is alive, not
    # once. Charging it once flatters them badly: a 60-day funded run on a $119/month
    # plan is $357 of fees, not $119. ~21 trading days to the month.
    if a.fee_is_monthly:
        months = np.ceil(np.maximum(days, 1) / 21.0)
        fees = a.fee_eval * months + a.fee_activation * passed
    else:
        fees = a.fee_eval + a.fee_activation * passed
    net = paid - fees
    ev = net.mean()

    # Bootstrap CI. Payout distributions are extremely skewed — most accounts pay
    # nothing and a few pay a lot — so the sample mean is far noisier than n suggests.
    bs = rng.choice(net, size=(400, n), replace=True).mean(axis=1)
    lo, hi = np.percentile(bs, [2.5, 97.5])

    npass = max(passed.sum(), 1)
    return dict(ev=ev, ev_lo=lo, ev_hi=hi, p_pass=passed.mean(),
                e_paid=paid.mean(), fee=fees.mean(),
                days=days.mean(), drag=drag.mean(),
                ev_week=ev / max(days.mean() / 5.0, 1e-9),
                p_mll=causes["mll"] / n, p_timeout=causes["timeout"] / n,
                p_trapped=trapped / npass)


def main():
    print("=" * 92)
    print("  CLOSED FORM  —  barriers and fee only, no payout rules")
    print("  EV = -fee + P(pass) x split x funded-MLL,   P(pass) = D/(D+T)")
    print("=" * 92)
    print(f"  {'account':<26} {'target':>7} {'MLL':>6} {'P(pass)':>8} "
          f"{'fee':>8} {'EV':>9}")
    print("  " + "-" * 88)
    cf = {}
    for a in ACCOUNTS:
        ev, p = closed_form(a)
        cf[a.name] = ev
        print(f"  {a.name:<26} {a.eval_target:>7.0f} {a.eval_mll:>6.0f} "
              f"{p:>8.3f} {a.fee_eval:>8.2f} {ev:>9.0f}")

    print()
    print("=" * 92)
    print("  SIMULATED  —  every researched rule switched on, p_denied = 0")
    print("  MNQ, 1:1, risk sized to the contract limit, 15-day eval cap")
    print("=" * 92)
    print(f"  {'account':<26} {'P(pass)':>8} {'theory':>7} {'E[paid]':>9} {'EV':>8} "
          f"{'EV/wk':>7} {'died':>6} {'ranout':>7} {'trapd':>6}")
    print("  " + "-" * 88)

    rows = []
    for a in ACCOUNTS:
        risk = max_risk(a, "MNQ")
        r = run_cell(a, "MNQ", 1.0, risk)
        rows.append((a, r))
        theory = a.eval_mll / (a.eval_mll + a.eval_target)
        print(f"  {a.name:<26} {r['p_pass']:>8.3f} {theory:>7.3f} {r['e_paid']:>9.0f} "
              f"{r['ev']:>8.0f} {r['ev_week']:>7.0f} {r['p_mll']:>6.2f} "
              f"{r['p_timeout']:>7.2f} {r['p_trapped']:>6.2f}")

    print()
    print("  died   = hit the MLL during the eval")
    print("  ranout = still alive at the 15-day cycle cap, written off")
    print("  trapd  = PASSED the eval and still never got one dollar out")
    print()
    print("  P(pass) sits BELOW theory everywhere. Two reasons, both real:")
    print("  the trailing MLL keeps the drawdown 2k below your PEAK rather than your")
    print("  start, so D never grows as you profit; and the 15-day cap writes off")
    print("  slow paths that gambler's ruin would eventually have counted as wins.")

    print()
    print("=" * 92)
    print("  FUNDED-STAGE SIZING  —  the stage that actually decides the answer")
    print("  Eval risk pinned at the contract limit (speed is free there).")
    print("  Funded risk swept DOWN, because the funded problem is survival, not speed.")
    print("=" * 92)
    print(f"  {'account':<26} " + "".join(f"{f'${r:.0f}':>9}" for r in FUNDED_GRID)
          + f"{'best':>9}")
    print("  " + "-" * 88)
    best_cfg = {}
    for a in ACCOUNTS:
        er = max_risk(a, "MNQ")
        # joint sweep: funded risk x funded trades-per-day
        best = (-1e9, None, None)
        row = []
        for fr in FUNDED_GRID:
            cell = max(
                run_cell(a, "MNQ", 1.0, er, n=2500, funded_risk=fr, funded_tpd=t)["ev"]
                for t in TPD_GRID
            )
            row.append(cell)
            for t in TPD_GRID:
                e = run_cell(a, "MNQ", 1.0, er, n=2500, funded_risk=fr,
                             funded_tpd=t)["ev"]
                if e > best[0]:
                    best = (e, fr, t)
        best_cfg[a.name] = best
        print(f"  {a.name:<26} " + "".join(f"{e:>9.0f}" for e in row)
              + f"{best[1]:>9.0f}")

    print()
    print("  Each cell is already the best trades-per-day for that risk level.")
    print(f"  Eval risk is ${max_risk(ACCOUNTS[0], 'MNQ'):.0f}. The two stages want")
    print("  sizes an order of magnitude apart.")
    print()
    print("  BEST JOINT CONFIG PER ACCOUNT")
    print(f"  {'account':<26} {'fundedRisk':>11} {'trades/day':>11} {'EV':>9}")
    print("  " + "-" * 88)
    for a in ACCOUNTS:
        e, fr, t = best_cfg[a.name]
        print(f"  {a.name:<26} {fr:>11.0f} {t:>11d} {e:>9.0f}")

    print()
    print("=" * 92)
    print("  REWARD:RISK  —  does the bracket shape matter?  (MNQ, max risk)")
    print("=" * 92)
    print(f"  {'account':<26} {'1:1 EV':>10} {'1:2 EV':>10} {'1:3 EV':>10}")
    print("  " + "-" * 88)
    for a in ACCOUNTS:
        risk = max_risk(a, "MNQ")
        evs = [run_cell(a, "MNQ", rr, risk, n=3000)["ev"] for rr in (1.0, 2.0, 3.0)]
        print(f"  {a.name:<26} {evs[0]:>10.0f} {evs[1]:>10.0f} {evs[2]:>10.0f}")

    print()
    print("=" * 92)
    print("  INSTRUMENT  —  MNQ vs NQ at the same dollar risk")
    print("  The contract limit caps both at the SAME dollar risk, so any difference")
    print("  is pure granularity: NQ moves in $200 lumps, MNQ in $20 lumps.")
    print("=" * 92)
    print(f"  {'account':<26} {'MNQ EV':>10} {'NQ EV':>10} {'MNQ P':>8} {'NQ P':>8}")
    print("  " + "-" * 88)
    for a in ACCOUNTS:
        m = run_cell(a, "MNQ", 1.0, max_risk(a, "MNQ"), n=3000)
        q = run_cell(a, "NQ", 1.0, max_risk(a, "NQ"), n=3000)
        print(f"  {a.name:<26} {m['ev']:>10.0f} {q['ev']:>10.0f} "
              f"{m['p_pass']:>8.3f} {q['p_pass']:>8.3f}")

    print()
    print("=" * 92)
    print("  DISCRETIONARY DENIAL  —  EV vs P(firm refuses the payout)")
    print("  Three of four firms name this strategy in their prohibited-practice docs.")
    print("  The break-even column is the denial rate at which the account turns -EV.")
    print("=" * 92)
    print(f"  {'account':<26} {'p=0':>9} {'p=0.10':>9} {'p=0.25':>9} "
          f"{'p=0.50':>9} {'breakeven':>10}")
    print("  " + "-" * 88)
    for a in ACCOUNTS:
        risk = max_risk(a, "MNQ")
        evs = {}
        for p in (0.0, 0.10, 0.25, 0.50):
            evs[p] = run_cell(a, "MNQ", 1.0, risk, n=3000, p_denied=p)["ev"]
        # EV is linear in p_denied: EV(p) = -fee + (1-p) * gross. Solve EV = 0.
        # EV(p) = -fee + (1-p)*gross, so break-even is p = 1 - fee/gross. If the gross
        # payout stream is already smaller than the fee, no denial rate makes it work —
        # it is negative even at p=0, and printing a negative "break-even" is nonsense.
        gross = evs[0.0] + a.fee_eval
        be_s = (f"{1.0 - a.fee_eval / gross:>10.2f}" if gross > a.fee_eval
                else f"{'never +EV':>10}")
        print(f"  {a.name:<26} {evs[0.0]:>9.0f} {evs[0.10]:>9.0f} "
              f"{evs[0.25]:>9.0f} {evs[0.50]:>9.0f} {be_s}")

    print()
    print("=" * 92)
    print("  HEADLINE  —  best config per account, n=20000, 95% bootstrap CI")
    print("  A CI straddling zero means NO measurable edge. Do not read the point")
    print("  estimate as a result when that happens.")
    print("=" * 92)
    print(f"  {'account':<26} {'EV':>8} {'95% CI':>18} {'EV/mo':>8} {'days':>6} "
          f"{'pass':>6} {'trapd':>6} {'verdict':>8}")
    print("  " + "-" * 88)
    final = []
    for a in ACCOUNTS:
        _, fr, t = best_cfg[a.name]
        r = run_cell(a, "MNQ", 1.0, max_risk(a, "MNQ"), n=20000,
                     funded_risk=fr, funded_tpd=t, seed=99)
        cycles_per_month = 21.0 / max(r["days"], 1.0)
        ev_mo = r["ev"] * cycles_per_month
        verdict = "+EV" if r["ev_lo"] > 0 else ("-EV" if r["ev_hi"] < 0 else "NOISE")
        final.append((a, r, ev_mo, verdict))
        print(f"  {a.name:<26} {r['ev']:>8.0f} "
              f"[{r['ev_lo']:>7.0f},{r['ev_hi']:>7.0f}] {ev_mo:>8.0f} "
              f"{r['days']:>6.1f} {r['p_pass']:>6.2f} {r['p_trapped']:>6.2f} "
              f"{verdict:>8}")

    print()
    print("  EV/mo assumes you re-buy immediately and run cycles back to back on ONE")
    print("  account. It does NOT assume parallel accounts.")

    print()
    print("=" * 92)
    print("  CAVEATS — read these before acting on any number above")
    print("=" * 92)
    for a in ACCOUNTS:
        if a.unverified:
            print(f"\n  {a.name}   [{a.source}]")
            for u in a.unverified:
                print(f"      - {u}")


if __name__ == "__main__":
    main()
