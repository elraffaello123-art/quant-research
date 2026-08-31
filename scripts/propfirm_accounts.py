"""
propfirm_accounts.py — the researched rulesets, transcribed.

EVERY NUMBER HERE CAME FROM A FIRM'S OWN HELP CENTRE OR TERMS, fetched 2026-07-20.
Where a firm contradicts itself, the `unverified` tuple says so and the code takes the
more authoritative / more recent page. Where a rule could not be found, it is left at
the dataclass default and listed in `unverified` — NOT guessed.

All accounts here are the $50K size, so the comparison is like-for-like. Instant-funding
variants are excluded throughout, per the brief.

READ THIS BEFORE TRUSTING ANY EV NUMBER
---------------------------------------
Prop rules change constantly. Several of these pages were edited within days of
2026-07-20. This file is a snapshot, not a live feed. Re-verify before committing money.

THE DISCRETIONARY-DENIAL PROBLEM
--------------------------------
Three of the four firms explicitly name this strategy in their prohibited-practices
documents. That is not a modelling nicety, it is the dominant risk:

  Alpha Futures  "Gambling tendencies or account rolling" is prohibited. Taking
                 "maximum leverage on a single position" with "no plan, no stop loss"
                 is "not tolerated". Buying accounts and repeating until one succeeds
                 is banned by name.
  FundedNext     "Account Rolling" — "purchasing multiple Challenge Accounts to rapidly
                 progress through probability rather than skill". "Account Flipping" —
                 "using excessive leverage to rapidly grow or blow up accounts".
  MFFU           Bans "exploiting the lack of slippage… tight brackets". Terms require
                 "consistency in position sizing, trade frequency, and overall risk
                 exposure" and prohibit conduct inconsistent with your trading history.
  Tradeify       Weakest language of the four: max contract size and DCA are
                 "discouraged", not prohibited. No explicit gambling clause found.

`p_payout_denied` is set to 0.0 in this file so the raw geometry is visible. The runner
sweeps it. Any EV quoted at p=0 is an upper bound that assumes the clauses are never
enforced — which is not what they are for.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "toolkit"))

from propsim import EOD_TRAIL, FirmRules  # noqa: E402


ACCOUNTS = [

    # -----------------------------------------------------------------------
    FirmRules(
        name="FundedNext Flex 50K",
        start_balance=50_000, fee_eval=69.99, fee_activation=0.0,
        eval_target=2_500, eval_mll=1_500, eval_mll_type=EOD_TRAIL, eval_trail_cap=100,
        eval_daily_loss=None, eval_min_days=0,
        funded_mll=1_500, funded_mll_type=EOD_TRAIL, funded_trail_cap=100,
        funded_daily_loss=None, profit_split=0.80,
        benchmark_days_required=5, benchmark_day_profit=200,
        payout_cycle_profit=500, payout_min_amount=250,
        payout_max_amount=1_500, payout_max_pct=0.50,
        payout_fee_pct=0.035, max_payouts=5,
        withdraw_moves_threshold=False, consistency_pct=None,
        max_contracts=3,
        source="helpfutures.fundednext.com, fetched 2026-07-20",
        unverified=("eval min trading days not stated anywhere — modelled as 0",
                    "5:1 max reward:risk enforced in Terms; not modelled",
                    "10s min hold (help centre) vs 15-20s (Terms) — conflict"),
    ),

    FirmRules(
        name="FundedNext Legacy 50K", fee_reset=183.99,
        start_balance=50_000, fee_eval=199.99, fee_activation=0.0,
        eval_target=3_000, eval_mll=2_000, eval_mll_type=EOD_TRAIL, eval_trail_cap=0,
        eval_daily_loss=None, eval_min_days=0,
        funded_mll=2_000, funded_mll_type=EOD_TRAIL, funded_trail_cap=0,
        funded_daily_loss=None, profit_split=0.80,
        benchmark_days_required=5, benchmark_day_profit=200,
        payout_cycle_profit=500, payout_min_amount=250,
        payout_max_amount=6_000, payout_max_pct=0.50,
        payout_fee_pct=0.035, max_payouts=None,
        withdraw_moves_threshold=False, consistency_pct=None,
        max_contracts=5,
        source="helpfutures.fundednext.com, fetched 2026-07-20",
        unverified=("no stated cap on total payouts — an ABSENCE, not a confirmation",
                    "Legacy freeze at initial balance (X=0) omitted from pass-criteria "
                    "article; taken from the MLL article"),
    ),

    # -----------------------------------------------------------------------
    FirmRules(
        name="MFFU Flex 50K", fee_reset=153.0,
        start_balance=50_000, fee_eval=153.0, fee_activation=0.0,
        eval_target=3_000, eval_mll=2_000, eval_mll_type=EOD_TRAIL, eval_trail_cap=100,
        eval_daily_loss=None, eval_min_days=2,
        funded_mll=2_000, funded_mll_type=EOD_TRAIL, funded_trail_cap=100,
        funded_daily_loss=None, profit_split=0.80,
        benchmark_days_required=5, benchmark_day_profit=150,
        payout_cycle_profit=500, payout_min_amount=250,
        payout_max_amount=2_000, payout_max_pct=0.50,
        payout_fee_pct=0.0, max_payouts=5,
        withdraw_moves_threshold=False, consistency_pct=None,
        max_contracts=3,
        source="help.myfundedfutures.com, fetched 2026-07-20",
        unverified=("eval fee monthly vs one-time NOT CONFIRMED (plans/flex 404'd)",
                    "max payout $2,000 (current guide) vs $5,000 (legacy) — conflict",
                    "eval max contracts 3 mini (May guide) vs 5 mini (June legacy page)",
                    "sim-funded, not real capital; 5 payouts then must go live"),
    ),

    FirmRules(
        name="MFFU Pro 50K", fee_reset=153.0,
        start_balance=50_000, fee_eval=157.0, fee_activation=0.0, fee_is_monthly=True,
        eval_target=3_000, eval_mll=2_000, eval_mll_type=EOD_TRAIL, eval_trail_cap=100,
        eval_daily_loss=None, eval_min_days=2,
        funded_mll=2_000, funded_mll_type=EOD_TRAIL, funded_trail_cap=100,
        funded_daily_loss=None, profit_split=0.80,
        benchmark_days_required=0, benchmark_day_profit=0,
        payout_min_profit=2_100, payout_min_days=14, payout_period_days=14,
        payout_min_amount=1_000, payout_max_amount=100_000,
        payout_fee_pct=0.0, max_payouts=None,
        withdraw_moves_threshold=False, consistency_pct=None,
        max_contracts=6,
        source="help.myfundedfutures.com + myfundedfutures.com/plans/pro, 2026-07-20",
        unverified=("fee $157 (per-size article) vs $114/mo promo vs $227/mo list",
                    "the one early 60%-of-profit withdrawal option is NOT modelled",
                    "sim-funded, not real capital"),
    ),

    # -----------------------------------------------------------------------
    FirmRules(
        name="Tradeify Growth 50K", fee_reset=95.0,
        start_balance=50_000, fee_eval=145.0, fee_activation=0.0,
        eval_target=3_000, eval_mll=2_000, eval_mll_type=EOD_TRAIL,
        eval_trail_cap=None,          # NO lock during eval — the trail chases forever
        eval_daily_loss=1_250, eval_min_days=1,
        funded_mll=2_000, funded_mll_type=EOD_TRAIL, funded_trail_cap=100,
        funded_daily_loss=1_250, daily_loss_is_soft=True, profit_split=0.90,
        benchmark_days_required=5, benchmark_day_profit=150,
        payout_min_profit=3_000,      # balance must reach $53,000
        payout_min_amount=500, payout_max_amount=1_500,
        payout_fee_pct=0.0, max_payouts=None,
        withdraw_moves_threshold=False, consistency_pct=0.35,
        max_contracts=4,
        source="help.tradeify.co, fetched 2026-07-20",
        unverified=("Essential-Rules page says NetLiq/intraday trailing, contradicting "
                    "the dedicated drawdown article (EOD). Took the EOD article.",
                    "150K DLL $3,750 eval vs $3,000 funded — unresolved, 50K unaffected",
                    "max payout is tiered by payout number; modelled at the payout-1 cap"),
    ),

    FirmRules(
        name="Tradeify Select Flex 50K", fee_reset=95.0,
        start_balance=50_000, fee_eval=165.0, fee_activation=0.0,
        eval_target=3_000, eval_mll=2_000, eval_mll_type=EOD_TRAIL,
        eval_trail_cap=None,          # no lock during eval
        eval_daily_loss=None, eval_min_days=3,
        eval_consistency_pct=0.40,    # same eval rule as Select Daily
        funded_mll=2_000, funded_mll_type=EOD_TRAIL, funded_trail_cap=100,
        funded_daily_loss=None, profit_split=0.90,
        benchmark_days_required=5, benchmark_day_profit=150,
        payout_min_profit=0.0,        # explicitly NO minimum balance — the most permissive found
        payout_min_amount=1.0, payout_max_amount=3_000, payout_max_pct=0.50,
        payout_cycle_profit=1.0,
        payout_fee_pct=0.0, max_payouts=None,
        withdraw_moves_threshold=False, consistency_pct=None,
        max_contracts=4,
        source="help.tradeify.co, fetched 2026-07-20",
        unverified=("funded stage starts at HALF the eval contract limit (2 mini), "
                    "scaling up at $1.5k/$2k/$3k/$4.5k equity — not modelled",
                    "requesting a payout instantly locks the drawdown at start+$100"),
    ),

    # -----------------------------------------------------------------------
    # Igor's pick. The key structural difference from Select Flex: payouts are DAILY
    # ELIGIBLE with NO benchmark/winning-day requirement, which removes the single
    # biggest EV leak found in the first pass. It pays for that with a hard $2,100
    # buffer you may not withdraw below, a $1,000 per-request cap, a 2x-cycle-profit
    # continuity rule, and a $1,000 daily loss limit.
    FirmRules(
        name="Tradeify Select Daily 50K", fee_reset=95.0,
        start_balance=50_000, fee_eval=165.0, fee_activation=0.0,
        eval_target=3_000, eval_mll=2_000, eval_mll_type=EOD_TRAIL,
        eval_trail_cap=None,          # no lock during eval
        eval_daily_loss=None, eval_min_days=3,
        eval_consistency_pct=0.40,    # blocks a one-big-trade pass
        funded_mll=2_000, funded_mll_type=EOD_TRAIL, funded_trail_cap=100,
        funded_daily_loss=1_000, daily_loss_is_soft=True, profit_split=0.90,
        benchmark_days_required=0, benchmark_day_profit=0,   # <- the whole point
        payout_min_profit=2_100,      # fixed buffer, may not withdraw below
        payout_period_days=1,         # daily eligibility
        payout_min_amount=250, payout_max_amount=1_000,
        payout_max_mult_cycle=2.0,    # Daily Continuity Rule
        payout_keep_buffer=2_100,
        payout_cycle_profit=1.0,      # cycle profit must be > 0
        payout_fee_pct=0.0, max_payouts=None,
        withdraw_moves_threshold=False, consistency_pct=None,
        max_contracts=4,
        source="help.tradeify.co Select Flex/Daily payout policies, fetched 2026-07-20",
        unverified=("funded starts at HALF eval contracts (2 mini), scaling at "
                    "$1.5k/$2k/$3k/$4.5k equity — NOT modelled, would make this worse",
                    "Select Daily min trading days before first payout not stated",
                    "eval 40% consistency modelled as 'keep trading until compliant'"),
    ),

    FirmRules(
        name="Alpha Zero 50K", fee_reset=109.0,
        start_balance=50_000, fee_eval=119.0, fee_activation=0.0, fee_is_monthly=True,
        eval_target=3_000, eval_mll=2_000, eval_mll_type=EOD_TRAIL,
        eval_trail_cap=0,             # freezes at STARTING BALANCE, and during eval too
        eval_daily_loss=1_000, eval_min_days=1,
        funded_mll=2_000, funded_mll_type=EOD_TRAIL, funded_trail_cap=0,
        funded_daily_loss=1_000, daily_loss_is_soft=True, profit_split=0.90,
        benchmark_days_required=5, benchmark_day_profit=200,
        payout_min_amount=200, payout_max_amount=1_500, payout_max_pct=0.50,
        payout_fee_pct=0.0, max_payouts=None,
        withdraw_moves_threshold=False,
        consistency_pct=0.40,         # activates in the FUNDED stage on Zero
        max_contracts=3,
        source="help.alpha-futures.com, fetched 2026-07-20",
        unverified=("monthly subscription continues on the funded account too",
                    "funded scaling starts at ONE mini until +$2,000 profit — not modelled",
                    "Zero funded adds news-trading restrictions absent in eval"),
    ),

    FirmRules(
        name="Alpha Advanced 50K",
        start_balance=50_000, fee_eval=209.0, fee_activation=0.0, fee_is_monthly=True,
        eval_target=4_000, eval_mll=1_750, eval_mll_type=EOD_TRAIL, eval_trail_cap=0,
        eval_daily_loss=None, eval_min_days=3,
        funded_mll=1_750, funded_mll_type=EOD_TRAIL, funded_trail_cap=0,
        funded_daily_loss=None, profit_split=0.90,
        benchmark_days_required=5, benchmark_day_profit=200,
        payout_min_amount=1_000, payout_max_amount=15_000, payout_max_pct=0.50,
        payout_fee_pct=0.0, max_payouts=None,
        withdraw_moves_threshold=False, consistency_pct=None,
        max_contracts=5,
        source="help.alpha-futures.com, fetched 2026-07-20",
        unverified=("40% consistency applies in EVAL on Advanced — not modelled",
                    "monthly subscription continues on the funded account"),
    ),
]


def by_name(name):
    for a in ACCOUNTS:
        if a.name == name:
            return a
    raise KeyError(name)
