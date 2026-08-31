"""
propsim_tests.py — self-test for the prop-account Monte Carlo.

    python3 toolkit/propsim_tests.py

Same discipline as `tests.py`: the simulator is only trustworthy if all of these pass,
because each one pins the sim against a result we can derive INDEPENDENTLY of the code.

    T1  driftless pass rate must equal D/(D+T)          (gambler's ruin)
    T2  lifetime extraction must equal distance to MLL  (optional stopping)
    T3  withdrawal policy must not change EV            (martingale invariance)
    T4  oversizing must degrade pass rate monotonically (barrier overshoot)
    T5  degenerate barriers must give P=0 and P=1       (sanity)

T1-T3 are the load-bearing ones. If the sim can reproduce those three it is measuring
the geometry correctly, and the firm-specific rule frictions layered on top are then
believable. If it CANNOT, every EV number this project produces is fiction.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from propsim import (  # noqa: E402
    EOD_TRAIL, INSTRUMENTS, STATIC, FirmRules, MLLTracker, Policy,
    _run_stage, simulate_account,
)

PASS, FAIL = "PASS", "FAIL"
results = []


def banner(t):
    print("\n" + "#" * 68)
    print(f"#  {t}")
    print("#" * 68)


def check(name, got, want, tol, note=""):
    ok = abs(got - want) <= tol
    results.append((name, ok))
    flag = PASS if ok else FAIL
    print(f"  [{flag}] {name}: got {got:.4f}  want {want:.4f}  (tol {tol})  {note}")
    return ok


def _free_rules(target=3000.0, mll=2000.0, mll_type=STATIC, **kw):
    """A ruleset with every friction switched OFF, so only the geometry is left.

    This is the control condition. Fees zero, no min days, no consistency rule, no
    daily loss limit, payouts always available. Anything the sim reports here has to
    be pure barrier mathematics.
    """
    base = dict(
        name="control", start_balance=50000.0, fee_eval=0.0, fee_activation=0.0,
        eval_target=target, eval_mll=mll, eval_mll_type=mll_type, eval_trail_cap=None,
        eval_daily_loss=None, eval_min_days=0,
        funded_mll=mll, funded_mll_type=mll_type, funded_trail_cap=None,
        funded_daily_loss=None, profit_split=1.0,
        payout_min_profit=0.0, payout_min_days=0, payout_min_amount=0.0,
        payout_period_days=1, payout_keep_buffer=0.0,
        withdraw_moves_threshold=False, consistency_pct=None,
    )
    base.update(kw)
    return FirmRules(**base)


# ---------------------------------------------------------------------------
def t1_gamblers_ruin():
    banner("T1  pass rate must equal D/(D+T)  — position size is irrelevant")
    print("  A driftless walk hits +T before -D with probability D/(D+T).")
    print("  We run three DIFFERENT risk sizes. All three must land on the same number.\n")
    ok_all = True
    for risk in (100.0, 250.0, 500.0):
        rules = _free_rules(target=3000.0, mll=2000.0)
        pol = Policy(rr=1.0, risk_per_trade=risk, stop_ticks=40,
                     trades_per_day=8, max_days=4000, eval_days_cap=4000)
        inst = dict(INSTRUMENTS["MNQ"]); inst["cost_rt"] = 0.0   # isolate geometry
        rng = np.random.default_rng(11)
        wins = sum(_run_stage(rules, pol, inst, "eval", rng)[0] == "passed"
                   for _ in range(4000))
        ok_all &= check(f"P(pass) at risk=${risk:.0f}", wins / 4000, 0.40, 0.030)
    return ok_all


def t2_lifetime_extraction():
    banner("T2  lifetime extraction must equal the distance to the MLL")
    print("  Optional stopping: total withdrawn + final balance = sum of steps, and a")
    print("  zero-edge walk has E[sum of steps] = 0. The account always dies, so the")
    print("  final balance is the threshold. Therefore E[withdrawn] = the MLL itself.")
    print("  Barrier OVERSHOOT makes the truth slightly ABOVE the MLL, never below.\n")
    rules = _free_rules(mll=2000.0)
    pol = Policy(rr=1.0, risk_per_trade=200.0, stop_ticks=40,
                 trades_per_day=8, max_days=6000, eval_days_cap=6000, keep_buffer=0.0)
    inst = dict(INSTRUMENTS["MNQ"]); inst["cost_rt"] = 0.0
    rng = np.random.default_rng(3)
    outs = [_run_stage(rules, pol, inst, "funded", rng, withdrawals=True)
            for _ in range(3000)]
    died = [f for o, f in outs if o == "timeout" or o == "dead"]
    mean_w = np.mean([f["withdrawn"] for f in died])
    return check("E[withdrawn]", mean_w, 2000.0, 260.0, "(overshoot pushes this up)")


def t3_policy_invariance():
    banner("T3  withdrawal POLICY must not change EV  — the martingale claim")
    print("  This is the strong claim from the plan: with a static MLL that does not")
    print("  move on withdrawal, hoarding profit and stripping it instantly must pay")
    print("  the SAME. If these differ, either the sim is wrong or a rule is breaking")
    print("  the martingale — and in this control ruleset there are no rules left.\n")
    inst = dict(INSTRUMENTS["MNQ"]); inst["cost_rt"] = 0.0
    means = {}
    for label, keep, first in [("strip instantly", 0.0, 0.0),
                               ("hoard to $1000", 1000.0, 1000.0),
                               ("hoard to $2500", 2500.0, 2500.0)]:
        rules = _free_rules(mll=2000.0)
        pol = Policy(rr=1.0, risk_per_trade=200.0, stop_ticks=40, trades_per_day=8,
                     max_days=6000, eval_days_cap=6000, keep_buffer=keep, first_payout_at=first)
        rng = np.random.default_rng(7)
        outs = [_run_stage(rules, pol, inst, "funded", rng, withdrawals=True)
                for _ in range(3000)]
        means[label] = np.mean([f["withdrawn"] for _, f in outs])
        print(f"      {label:18s} E[withdrawn] = ${means[label]:8.0f}")
    spread = max(means.values()) - min(means.values())
    print()
    return check("spread across policies", spread, 0.0, 260.0,
                 "(must be flat — policy is not supposed to matter)")


def t4_overshoot():
    banner("T4  oversizing must DEGRADE pass rate  — barrier overshoot")
    print("  The one way size DOES touch EV. Huge bets jump past the MLL instead of")
    print("  landing on it, wasting drawdown room. Pass rate must fall monotonically")
    print("  as risk grows, and must never rise above the D/(D+T) ceiling of 0.40.\n")
    rates = []
    for risk in (100.0, 500.0, 1000.0, 1800.0):
        rules = _free_rules(target=3000.0, mll=2000.0)
        pol = Policy(rr=1.0, risk_per_trade=risk, stop_ticks=40,
                     trades_per_day=8, max_days=4000, eval_days_cap=4000)
        inst = dict(INSTRUMENTS["NQ"]); inst["cost_rt"] = 0.0
        rng = np.random.default_rng(5)
        wins = sum(_run_stage(rules, pol, inst, "eval", rng)[0] == "passed"
                   for _ in range(3000))
        rates.append(wins / 3000)
        print(f"      risk ${risk:6.0f}  ->  P(pass) {wins/3000:.3f}")
    mono = all(rates[i] >= rates[i + 1] - 0.02 for i in range(len(rates) - 1))
    ceil_ok = max(rates) <= 0.42
    ok = mono and ceil_ok
    results.append(("overshoot monotone + under ceiling", ok))
    print(f"\n  [{PASS if ok else FAIL}] monotone={mono}  under-ceiling={ceil_ok}")
    return ok


def t5_sanity():
    banner("T5  lopsided barriers  — must still track D/(D+T), not 0 and 1")
    print("  Note the expected values are NOT 0.0 and 1.0. With D=50000 and T=300 the")
    print("  theory is 50000/50300 = 0.994, and the residual 0.6% is real. Asserting")
    print("  1.0 here would be asserting something false.")
    print("  We also report the TIMEOUT rate, because a path that never resolves is")
    print("  scored as a non-pass and would silently drag the measured rate down.\n")
    inst = dict(INSTRUMENTS["MNQ"]); inst["cost_rt"] = 0.0
    ok = True

    for target, mll, seed in [(50000.0, 300.0, 1), (300.0, 50000.0, 2)]:
        rules = _free_rules(target=target, mll=mll)
        # max_days must be generous: expected steps to resolution is ~ (D*T)/step^2,
        # which for the lopsided case is large. Too small a cap fakes a failure.
        pol = Policy(rr=1.0, risk_per_trade=100.0, stop_ticks=40, trades_per_day=8,
                     max_days=30000, eval_days_cap=30000)
        rng = np.random.default_rng(seed)
        outs = [_run_stage(rules, pol, inst, "eval", rng)[0] for _ in range(600)]
        rate = sum(o == "passed" for o in outs) / 600
        timeouts = sum(o == "timeout" for o in outs) / 600
        theory = mll / (mll + target)
        ok &= check(f"P(pass) T={target:.0f} D={mll:.0f}", rate, theory, 0.03,
                    f"(timeouts {timeouts:.1%})")
    return ok


def t6_tracker_units():
    banner("T6  MLLTracker mechanics  — unit checks on the freeze and the withdrawal")
    ok = True

    # static never moves
    t = MLLTracker(2000.0, STATIC, None)
    t.on_equity(5000.0); t.on_day_close(5000.0)
    ok &= check("static threshold after +5000", t.threshold, -2000.0, 1e-9)

    # EOD trail ratchets only on close, and freezes at the cap
    t = MLLTracker(2000.0, EOD_TRAIL, 100.0)
    t.on_equity(1500.0)
    ok &= check("EOD trail ignores intraday equity", t.threshold, -2000.0, 1e-9)
    t.on_day_close(1500.0)
    ok &= check("EOD trail after close at +1500", t.threshold, -500.0, 1e-9)
    t.on_day_close(9000.0)
    ok &= check("EOD trail FROZEN at cap +100", t.threshold, 100.0, 1e-9)

    # the rule that decides whether payouts are free
    t = MLLTracker(2000.0, STATIC, None)
    t.on_withdrawal(500.0, moves=False)
    ok &= check("threshold when withdrawal does NOT move it", t.threshold, -2000.0, 1e-9)
    t.on_withdrawal(500.0, moves=True)
    ok &= check("threshold when withdrawal DOES move it", t.threshold, -2500.0, 1e-9)
    return ok


if __name__ == "__main__":
    t1_gamblers_ruin()
    t2_lifetime_extraction()
    t3_policy_invariance()
    t4_overshoot()
    t5_sanity()
    t6_tracker_units()

    banner("SUMMARY")
    bad = [n for n, ok in results if not ok]
    for n, ok in results:
        print(f"  [{PASS if ok else FAIL}] {n}")
    print()
    if bad:
        print(f"  {len(bad)} FAILED -> the simulator is NOT trustworthy yet.")
        sys.exit(1)
    print("  All checks passed. Geometry is being measured correctly.")
