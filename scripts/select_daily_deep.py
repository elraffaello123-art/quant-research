"""
select_daily_deep.py — Igor's plan, scored properly.

THE PLAN AS STATED
  - Pass a Tradeify Select 50K eval (~33% claimed)
  - Funded: DLL is $1,000 and MLL is $2,000, so "two tries" at a 3RR win
  - Risk $1,000 to make $3,000, request $1,000, keep the account, rinse

WHY THIS ACCOUNT DESERVED A SECOND LOOK
  Select DAILY has daily payout eligibility with NO benchmark/winning-day requirement.
  In the first pass, the ~5-winning-days gate was the single biggest EV leak — it
  trapped 36-81% of accounts that had already passed. Select Daily removes it.

WHAT IT CHARGES FOR THAT
  - a fixed $2,100 buffer you may not withdraw below
  - $1,000 cap per request
  - the Daily Continuity Rule: max 2x profit since your last payout
  - a $1,000 daily loss limit (soft: locks the session, does not kill the account)
  - a 40% consistency rule and 3-day minimum IN THE EVAL

Run: python3 scripts/select_daily_deep.py
"""
import os
import sys
from dataclasses import replace

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "toolkit"))
sys.path.insert(0, HERE)

from propfirm_accounts import by_name                       # noqa: E402
from propsim import Policy, _run_stage, simulate_account, INSTRUMENTS  # noqa: E402

A = by_name("Tradeify Select Daily 50K")
INST = INSTRUMENTS["MNQ"]
N = 20000


def bar(t):
    print("\n" + "=" * 90)
    print("  " + t)
    print("=" * 90)


def funded_only(risk, rr, tpd=1, n=N, seed=1, days=90):
    """Score the FUNDED stage in isolation, assuming you are already through the eval.

    Separating the stages matters: the eval is a one-off toll, while the funded stage
    is the thing that either does or does not 'make a living'.
    """
    pol = Policy(rr=rr, risk_per_trade=risk, stop_ticks=40, trades_per_day=tpd,
                 max_days=days, eval_days_cap=15)
    rng = np.random.default_rng(seed)
    out = [_run_stage(A, pol, INST, "funded", rng, withdrawals=True) for _ in range(n)]
    w = np.array([f["withdrawn"] for _, f in out])
    d = np.array([f["days"] for _, f in out])
    return w, d


def main():
    print(__doc__)

    # ---------------------------------------------------------------
    bar("STEP 1 — the ceiling, before any simulation")
    print("""
  A zero-edge funded account is a driftless walk with an absorbing floor. By optional
  stopping, E[total ever withdrawn] = the distance from where you start to that floor.
  No withdrawal schedule beats it; this is a bound, not a strategy choice.

  Funded start   $50,000      floor (MLL)  $48,000      distance  $2,000
  Your 90% share of $2,000                              =  $1,800   <-- lifetime ceiling

  But you cannot touch anything until you are above the $2,100 buffer. So first you
  must travel +$2,100 while never going -$2,000. For a driftless walk that is
      P = 2000 / (2000 + 2100) = 0.488
  and the trailing MLL makes the true number worse than that.

  So before costs, before the eval fee:
      E[extraction] <= 0.488 x $1,800 = $878
  Against a $165 eval fee that only clears if P(pass eval) is high. It is not.
""")

    # ---------------------------------------------------------------
    bar("STEP 2 — your exact funded plan: risk $1,000 at 3RR, 1 trade/day")
    w, d = funded_only(risk=1000, rr=3.0, tpd=1)
    print(f"""
  E[gross withdrawn]      ${w.mean():8.0f}
  E[your 90% share]       ${w.mean() * 0.90:8.0f}
  P(extract nothing)       {(w == 0).mean():8.1%}
  P(extract >= $1,000)     {(w >= 1000).mean():8.1%}
  median withdrawn        ${np.median(w):8.0f}
  mean days alive          {d.mean():8.1f}
""")
    print("  The 'two tries' reading is right, and it is the problem. Risking $1,000")
    print("  against a $1,000 DLL means one trade per day, and a $2,000 MLL means two")
    print("  losing days ends the account. You get 2 shots at a 25% event:")
    print("      P(at least one 3RR win) = 1 - 0.75^2 = 43.8%")
    print("  and a win on the SECOND day only reaches $52,000 — still $100 under the")
    print("  $2,100 buffer, so it does not even unlock a payout on its own.")

    # ---------------------------------------------------------------
    bar("STEP 3 — is $1,000 at 3RR the best funded config? sweep it")
    print(f"\n  {'risk':>7} {'rr':>5} {'t/day':>6} {'E[gross]':>10} {'P(zero)':>9} "
          f"{'E[90%]':>9} {'days':>7}")
    print("  " + "-" * 78)
    best = (-1, None)
    for risk in (1000, 700, 500, 350, 250, 150):
        for rr in (1.0, 2.0, 3.0):
            tpd = 1 if risk >= 500 else 2
            w, d = funded_only(risk, rr, tpd, n=6000)
            share = w.mean() * 0.90
            if share > best[0]:
                best = (share, (risk, rr, tpd))
            print(f"  {risk:>7} {rr:>5.0f} {tpd:>6} {w.mean():>10.0f} "
                  f"{(w == 0).mean():>8.1%} {share:>9.0f} {d.mean():>7.1f}")
    print(f"\n  best funded config: risk ${best[1][0]}, {best[1][1]:.0f}RR, "
          f"{best[1][2]} trade/day  ->  E[your share] ${best[0]:.0f}")

    # ---------------------------------------------------------------
    bar("STEP 4 — the EVAL, played competently: coast after target, spread the profit")
    print("""
  The 40% consistency rule means one big day cannot pass you: a $3,000 single-day
  profit needs $7,500 total to comply. The fix is not to trade bigger, it is to trade
  SMALLER and let the profit land across three or more days. So sweep eval risk.
""")
    print(f"  {'evalRisk':>9} {'t/day':>6} {'P(pass)':>9} {'days':>7}")
    print("  " + "-" * 78)
    best_eval = (-1, None)
    for erisk in (600, 400, 300, 200, 150, 100):
        for etpd in (1, 2, 4):
            pol = Policy(rr=1.0, risk_per_trade=erisk, stop_ticks=40,
                         trades_per_day=etpd, max_days=90, eval_days_cap=15)
            rng = np.random.default_rng(5)
            outs = [_run_stage(A, pol, INST, "eval", rng)[0] for _ in range(4000)]
            p = sum(o == "passed" for o in outs) / 4000
            if p > best_eval[0]:
                best_eval = (p, (erisk, etpd))
            if etpd == 2:
                print(f"  {erisk:>9} {etpd:>6} {p:>9.3f}")
    print(f"\n  best eval config: risk ${best_eval[1][0]}, {best_eval[1][1]} trades/day"
          f"  ->  P(pass) {best_eval[0]:.3f}")
    print(f"  (Igor's estimate was 0.33; gambler's-ruin ceiling is 0.40)")

    bar("STEP 5 — full cycle, BEST eval config x BEST funded config")
    erisk, etpd = best_eval[1]
    frisk, frr, ftpd = best[1]
    for label, econs in [("as researched (40% eval consistency)", 0.40),
                         ("if the 40% rule did NOT exist", None)]:
        rules = replace(A, eval_consistency_pct=econs)
        pol = Policy(rr=1.0, risk_per_trade=erisk, stop_ticks=40, trades_per_day=etpd,
                     funded_risk_per_trade=frisk, funded_trades_per_day=ftpd,
                     max_days=90, eval_days_cap=15)
        rng = np.random.default_rng(5)
        res = [simulate_account(rules, pol, "MNQ", rng) for _ in range(N)]
        paid = np.array([r.paid for r in res])
        passed = np.array([r.passed for r in res])
        days = np.array([r.days for r in res])
        ev = paid.mean() - A.fee_eval
        bs = np.random.default_rng(0).choice(paid - A.fee_eval, size=(400, N)).mean(1)
        lo, hi = np.percentile(bs, [2.5, 97.5])
        print(f"\n  {label}")
        print(f"      P(pass eval)      {passed.mean():8.3f}")
        print(f"      E[paid to you]   ${paid.mean():8.0f}")
        print(f"      eval fee         ${A.fee_eval:8.2f}")
        print(f"      EV per cycle     ${ev:8.0f}   95% CI [{lo:.0f}, {hi:.0f}]")
        print(f"      mean days         {days.mean():8.1f}")
        v = "+EV" if lo > 0 else ("-EV" if hi < 0 else "NOISE")
        print(f"      verdict           {v:>8}")

    # ---------------------------------------------------------------
    bar("STEP 5 — 'the account remains mine for further rinsing'")
    w, _ = funded_only(risk=best[1][0], rr=best[1][1], tpd=best[1][2])
    got = w[w > 0]
    print(f"""
  Of accounts that extract anything at all:
      mean total extracted   ${got.mean():.0f}
      p90                    ${np.percentile(got, 90):.0f}
      p99                    ${np.percentile(got, 99):.0f}
      max seen               ${got.max():.0f}

  Rinsing does not compound. Every payout takes cash OUT of the account while the
  floor stays where it is, so each withdrawal moves you closer to death by exactly
  the amount you took. That is the optional-stopping bound in Step 1 doing its work:
  total extraction is capped by the distance to the floor, however you schedule it.

  To 'make a living' at $4,000/month you would need ~{4000 / max(got.mean() * 0.9, 1):.0f}
  accounts reaching payout every month, and only ~{(w > 0).mean():.0%} of funded
  accounts get there at all.
""")


if __name__ == "__main__":
    main()
