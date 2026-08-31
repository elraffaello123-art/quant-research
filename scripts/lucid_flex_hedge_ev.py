"""
lucid_flex_hedge_ev.py — Igor's "hedge the eval with a live account" business, priced
honestly against the REAL Lucid 50K Flex ruleset. Commissions ON, slippage OFF (per Igor).

THE IDEA BEING TESTED
---------------------
Farm cheap Lucid 50K Flex evals ($130, a capped-downside call option on a funded account).
Take the opposite side of every prop trade on a real live account, sized at ratio h of the
prop size. Claim: losing branches get covered by the hedge, winning branches cash out
payouts, so the business is +EV.

WHAT WE PROVED ALGEBRAICALLY LAST (and this script confirms)
-----------------------------------------------------------
The live hedge mirrors a driftless coinflip, so by optional stopping its expected MARKET
P&L is EXACTLY ZERO for any hedge ratio h. The hedge does not touch the mean — it only
reshuffles outcomes across branches (big +live in the fail branch, big -live in the payout
branch) and, because it doubles the traded size, ADDS commission. So:

    business_EV(h) = prop_EV  -  h * (live commission drag)     <- decreasing in h

i.e. the EV-maximising hedge is h = 0 (don't hedge; hedging only buys variance reduction
at a commission cost). The whole business therefore lives or dies on ONE number: the
prop account's own EV = -fee + P(pass) * P(payout) * net_payout - prop_commissions.

RULES USED (pulled 2026-07-23; see the message thread for sources)
------------------------------------------------------------------
  eval:   target +$3,000 | MLL $2,000 EOD-trailing, freezes at start-$100 | min 2 days |
          50% eval consistency (biggest day <= 50% of total profit at pass)
  funded: 90/10 split | EOD-trailing MLL, frozen | no consistency, no daily loss limit
  payout: 5 winning days each >= $150 | min $500 to withdraw |
          first payout = min($2,000, 50% of profit) | up to 5 payouts, then LucidLive
  cost:   NQ $3.50/round-turn, MNQ $1.00/round-turn — on BOTH accounts. No slippage.

Reuses the tested engine in toolkit/propsim.py (run toolkit/propsim_tests.py first).

Run: python3 scripts/lucid_flex_hedge_ev.py            # $130 fee, MNQ
     python3 scripts/lucid_flex_hedge_ev.py --fee 65   # discount-code fee
     python3 scripts/lucid_flex_hedge_ev.py --inst NQ
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "toolkit"))

from propsim import EOD_TRAIL, INSTRUMENTS, FirmRules, Policy, simulate_account  # noqa: E402

STOP_TICKS = 40
HEDGE_RATIOS = [0.0, 0.1, 0.3, 0.5, 1.0]
EVAL_DAYS_CAP = 30      # Lucid gives UNLIMITED eval time; 30 is a fair campaign-turnover cap
FUNDED_MAX_DAYS = 60


def lucid_50k_flex(fee):
    """Lucid 50K Flex, transcribed from the 2026-07-23 pull. Fields not published are
    left at engine defaults and called out below."""
    return FirmRules(
        name="Lucid Flex 50K",
        start_balance=50_000, fee_eval=fee, fee_activation=0.0, fee_reset=fee,
        eval_target=3_000, eval_mll=2_000, eval_mll_type=EOD_TRAIL, eval_trail_cap=100,
        eval_daily_loss=None, eval_min_days=2, eval_consistency_pct=0.50,
        funded_mll=2_000, funded_mll_type=EOD_TRAIL, funded_trail_cap=100,
        funded_daily_loss=None, profit_split=0.90,
        # Lucid's documented edge: the MLL is checked on the CLOSE, not intraday. A day
        # that dips $2k underwater and closes green survives. This is more accurate than
        # the engine default (intraday) AND it raises P(pass) — fairer to the scheme.
        breach_on_unrealized=False,
        benchmark_days_required=5, benchmark_day_profit=150,      # 5 days each >= $150
        payout_min_amount=500,                                   # min $500 to withdraw
        payout_max_amount=2_000, payout_max_pct=0.50,            # min($2,000, 50% profit)
        payout_cycle_profit=0.0, payout_fee_pct=0.0, max_payouts=5,
        withdraw_moves_threshold=False, consistency_pct=None,    # NO funded consistency
        max_contracts=15,
        source="phidias/saveonpropfirms/proptradingvibes + lucid help centre, 2026-07-23",
        unverified=(
            "eval fee $130 list / ~$65 with code — swept via --fee",
            "max_contracts 15 mini is a placeholder; eval pass prob is size-invariant so "
            "it barely matters, but funded survival sizing assumes room to size DOWN",
            "payout cap: modelled min($2,000, 50% of profit); 6th payout -> LucidLive "
            "not modelled (max_payouts=5)",
        ),
    )


def run(rules, pol, inst_name, n, seed):
    """Monte Carlo n full account lifecycles, collecting the per-trade path for hedging."""
    rng = np.random.default_rng(seed)
    paid = np.zeros(n)
    passed = np.zeros(n, bool)
    sum_pnl = np.zeros(n)       # total market P&L of the prop path (what the hedge mirrors)
    cost = np.zeros(n)          # prop commission drag
    payouts = np.zeros(n)
    for k in range(n):
        r = simulate_account(rules, pol, inst_name, rng, collect_pnls=True)
        paid[k] = r.paid
        passed[k] = r.passed
        sum_pnl[k] = sum(r.trade_pnls)
        cost[k] = r.cost_drag
        payouts[k] = r.n_payouts
    return dict(paid=paid, passed=passed, sum_pnl=sum_pnl, cost=cost, payouts=payouts)


def boot_ci(net, rng, reps=400):
    bs = rng.choice(net, size=(reps, net.size), replace=True).mean(axis=1)
    return np.percentile(bs, [2.5, 97.5])


def business_net(sim, rules, h, live_cost_ratio):
    """Real cash per run at hedge ratio h.

        net = (paid - fee)                      prop side, after 90/10 split
            + (-h * sum_pnl)                    live hedge MARKET P&L (zero mean)
            + (-h * cost * live_cost_ratio)     live hedge commission (same #trades)
    """
    fee = rules.fee_eval + rules.fee_activation * sim["passed"]
    prop = sim["paid"] - fee
    live_market = -h * sim["sum_pnl"]
    live_comm = -h * sim["cost"] * live_cost_ratio
    return prop + live_market, live_comm, prop


def pick_config(rules, inst_name):
    """Give the scheme its BEST shot: jointly sweep eval risk (speed vs overshoot) and
    funded risk/trades (survival), maximise prop EV. Eval pass prob is size-invariant in
    isolation, but overshoot past the MLL and the funded survival problem are not, so the
    sizes that win the two stages differ and both are swept."""
    best = (-1e9, None)
    for er in (300, 400, 500, 600):
        for fr in (250, 150, 100, 50):
            for tpd in (1, 2):
                pol = Policy(rr=1.0, risk_per_trade=er, funded_risk_per_trade=fr,
                             stop_ticks=STOP_TICKS, trades_per_day=4,
                             funded_trades_per_day=tpd,
                             max_days=FUNDED_MAX_DAYS, eval_days_cap=EVAL_DAYS_CAP)
                sim = run(rules, pol, inst_name, n=4000, seed=1)
                ev = (sim["paid"] - rules.fee_eval).mean()
                if ev > best[0]:
                    best = (ev, (er, fr, tpd))
    return best[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fee", type=float, default=130.0, help="eval fee ($130 list, ~65 code)")
    ap.add_argument("--inst", default="MNQ", choices=list(INSTRUMENTS))
    ap.add_argument("--n", type=int, default=30000)
    ap.add_argument("--live-cost-ratio", type=float, default=1.0,
                    help="live-broker RT cost / Lucid RT cost (1.0 = same)")
    args = ap.parse_args()

    print(__doc__)
    rules = lucid_50k_flex(args.fee)
    inst = INSTRUMENTS[args.inst]
    er, fr, tpd = pick_config(rules, args.inst)

    print("=" * 90)
    print(f"  LUCID 50K FLEX  |  instrument {args.inst}  |  eval fee ${args.fee:.0f}  |  "
          f"commissions ${inst['cost_rt']:.2f}/RT, no slippage")
    print(f"  BEST-EV config: eval risk ${er}/trade | funded risk ${fr}/trade, "
          f"{tpd} trade(s)/day | eval cap {EVAL_DAYS_CAP}d | n={args.n}")
    print("=" * 90)

    pol = Policy(rr=1.0, risk_per_trade=er, funded_risk_per_trade=fr,
                 stop_ticks=STOP_TICKS, trades_per_day=4, funded_trades_per_day=tpd,
                 max_days=FUNDED_MAX_DAYS, eval_days_cap=EVAL_DAYS_CAP)
    sim = run(rules, pol, args.inst, args.n, seed=99)
    rng = np.random.default_rng(7)

    p_pass = sim["passed"].mean()
    p_payout = (sim["payouts"] >= 1).mean()
    e_payouts = sim["payouts"].mean()
    e_paid_funded = sim["paid"][sim["passed"]].mean() if sim["passed"].any() else 0.0

    print(f"\n  PROP SIDE (this is the whole business — the hedge cannot raise it)")
    print(f"    P(pass eval)              {p_pass:6.3f}   (STATIC-floor barrier = "
          f"{rules.eval_mll/(rules.eval_mll+rules.eval_target):.3f}; real is lower because")
    print(f"                                       the EOD-TRAILING floor chases your peak)")
    print(f"    P(>=1 payout | any acct)  {p_payout:6.3f}")
    print(f"    E[payouts per account]    {e_payouts:6.3f}")
    print(f"    E[banked | passed], 90%   ${e_paid_funded:7.0f}")

    print(f"\n  BUSINESS EV vs HEDGE RATIO h   (mean real $ per account attempt, 95% CI)")
    print(f"    {'h':>5} {'live mkt (mean)':>16} {'live comm':>11} {'EV':>9} "
          f"{'95% CI':>20} {'std':>9}")
    print("    " + "-" * 76)
    ev0 = None
    for h in HEDGE_RATIOS:
        net_mkt, live_comm, prop = business_net(sim, rules, h, args.live_cost_ratio)
        net = net_mkt + live_comm
        ev = net.mean()
        if h == 0.0:
            ev0 = ev
        lo, hi = boot_ci(net, rng)
        live_market_mean = (net_mkt - prop).mean()      # = mean(-h*sum_pnl)
        print(f"    {h:>5.1f} {live_market_mean:>16.1f} {live_comm.mean():>11.1f} "
              f"{ev:>9.1f} [{lo:>7.1f},{hi:>7.1f}] {net.std():>9.0f}")

    print(f"\n    Read the 'live mkt (mean)' column: it stays ~0 at every h (optional-stopping")
    print(f"    zero-mean). The hedge's ONLY effect on EV is the negative 'live comm' column.")
    print(f"    So EV is highest at h=0 and falls as you hedge more. The hedge buys a smaller")
    print(f"    'std' (last column) — variance reduction — and pays for it in commission.")

    # Branch decomposition at h=0.1 — speaks to Igor's "+200 when I lose" intuition.
    h = 0.1
    net_mkt, live_comm, prop = business_net(sim, rules, h, args.live_cost_ratio)
    net = net_mkt + live_comm
    failed = ~sim["passed"]
    paidout = sim["payouts"] >= 1
    passed_nopay = sim["passed"] & (sim["payouts"] == 0)
    print(f"\n  BRANCH DECOMPOSITION at h={h}  (your 'heads I win / tails the hedge covers me')")
    print(f"    {'branch':<26} {'prob':>7} {'live mkt':>10} {'business net':>13}")
    print("    " + "-" * 60)
    for lbl, mask in [("eval FAILS", failed),
                      ("passed, NO payout", passed_nopay),
                      ("passed, >=1 payout", paidout)]:
        if mask.any():
            print(f"    {lbl:<26} {mask.mean():>7.3f} "
                  f"{(-h*sim['sum_pnl'][mask]).mean():>10.1f} {net[mask].mean():>13.1f}")
    print(f"\n    The fail branch really does pay the hedge (+live mkt). But average the")
    print(f"    branches weighted by prob and it nets to the prop EV above — the payout")
    print(f"    branch's big negative live mkt is exactly what funds the fail branch.")

    # Discretionary payout denial. Farming eval after eval to "progress through
    # probability rather than skill" is named as a prohibited practice at multiple firms;
    # a voided payout is a total loss of that cash. EV is linear in the denial rate, so
    # the break-even rate is the honest measure of how thin the +EV (if any) is.
    from dataclasses import replace
    gross_paid = sim["paid"].mean()                 # expected banked payout per attempt
    fee_only = rules.fee_eval + rules.fee_activation * p_pass
    print(f"\n  PAYOUT-DENIAL SENSITIVITY (h=0; 'account rolling' is a named prohibited practice)")
    print(f"    {'p_denied':>9} {'EV':>9}")
    print("    " + "-" * 22)
    for pd in (0.0, 0.10, 0.156, 0.25, 0.50):
        print(f"    {pd:>9.3f} {(1.0 - pd) * gross_paid - fee_only:>9.1f}")
    if gross_paid > fee_only:
        be = 1.0 - fee_only / gross_paid
        print(f"    break-even denial rate = {be:.1%}  -> above this, the whole scheme is -EV")
    else:
        print(f"    already -EV at zero denial; no denial rate rescues it")

    verdict = "+EV" if ev0 > 0 else "-EV / break-even"
    print("\n" + "=" * 90)
    print(f"  VERDICT: best-case business EV (h=0, no hedge) = ${ev0:.0f} per attempt  ->  {verdict}")
    print(f"  Hedging can only lower it (commission). Matches project-coinflip-prop-ev-negative.")
    print("=" * 90)


if __name__ == "__main__":
    main()
