"""
propfirm_daily_accounts.py — the DAILY-PAYOUT generation of prop accounts, transcribed.

Researched 2026-08-20. All $50K so the comparison is like-for-like. These are the accounts
that pay out every 24 hours, which is a different geometry from the 5-winning-day accounts
in `propfirm_accounts.py`: daily payouts let you strip the account down to the locked
threshold much faster, which is the whole reason they are interesting for a coinflip.

SOURCES ARE OFFICIAL HELP-CENTRE PAGES WHERE THEY EXIST. Every conflict between a firm's
own page and a third-party guide is recorded in `unverified` and resolved toward the firm.

THE ONE STRUCTURAL FACT THAT ORGANISES ALL OF THESE
---------------------------------------------------
On every firm here the payout buffer equals the max loss limit plus $100 — the exact
amount that trails the drawdown out to its lock point. That is not a coincidence:

    you cannot withdraw a dollar until you have pushed the threshold to its permanent
    floor, and once it is there your remaining distance to death is $100.

So the first payout and the trail-lock are the SAME event. Everything after that is
played from a $100 cushion. This is the geometry the daily-payout structure actually sells.

THE INTRADAY vs EOD QUESTION (Igor's, 2026-08-20)
-------------------------------------------------
MFFU Rapid and Rapid EOD are the controlled experiment: identical target, identical MLL,
identical payout terms, differing ONLY in the funded-stage trail — and in the price the
firm charges for it, which is paid in rules, not dollars:
    Rapid      funded INTRADAY trail, min 2 days, 50% eval consistency, 5 minis
    Rapid EOD  funded EOD      trail, min 4 days, 30% eval consistency, 3 minis
LucidDaily is the second experiment: the EVAL drawdown type is a checkout toggle with a
published price difference ($136 intraday vs $165 EOD at 50K, DLL on).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "toolkit"))

from propsim import EOD_TRAIL, INTRADAY_TRAIL, FirmRules  # noqa: E402


DAILY_ACCOUNTS = [

    # =======================================================================
    # MFFU RAPID 50K -- funded stage trails INTRADAY. The one Igor asked about.
    # help.myfundedfutures.com/en/articles/13134709-rapid-plan-50k-a-comprehensive-look
    # =======================================================================
    FirmRules(
        name="MFFU Rapid 50K (intraday)",
        start_balance=50_000,
        fee_eval=157.0, fee_is_monthly=True, fee_activation=0.0, fee_reset=157.0,

        eval_target=3_000, eval_mll=2_000,
        eval_mll_type=EOD_TRAIL, eval_trail_cap=100,
        eval_daily_loss=None, eval_min_days=2, eval_consistency_pct=0.50,

        funded_mll=2_000,
        funded_mll_type=INTRADAY_TRAIL, funded_trail_cap=100,
        funded_daily_loss=None,
        breach_on_unrealized=True,          # intraday trail off the equity high-water mark
        profit_split=0.90,

        payout_min_profit=2_100,            # the buffer == MLL + 100 == the lock point
        payout_min_days=1,                  # "exactly 24 hours after your first trade"
        payout_period_days=1,               # daily cadence
        payout_min_amount=500.0,
        payout_max_amount=None,             # firm states no cap
        payout_keep_buffer=2_100.0,         # must be ABOVE buffer to request AND remain
        payout_cycle_profit=0.0,
        benchmark_days_required=0, benchmark_day_profit=0.0,
        max_payouts=None,
        withdraw_moves_threshold=False,
        consistency_pct=None,               # "None in Sim Funded"
        max_contracts=5,

        source="help.myfundedfutures.com Rapid Plan 50k (official), fetched 2026-08-20",
        unverified=(
            "BUFFER: modelled as must be ABOVE it to request AND must REMAIN above it "
            "after (Igor, 2026-08-20 -- this is how these accounts actually work). The "
            "firm's page only states the buffer is required before the first request.",
            "fee $157/mo (test-max) not confirmed on an official page; 50% promo codes exist",
            "no stated per-request cap is an ABSENCE, not a confirmation",
            "sim-funded, not real capital; Rapid Live only after a $10k net-profit day",
            "funded stage bans T1 news (FOMC/CPI/NFP) 2 min either side -- not modelled, "
            "it removes trading windows rather than changing the geometry",
            "eval 50% consistency is soft (trade on until the best day dilutes); modelled "
            "as keep-trading-until-compliant, which matches",
        ),
    ),

    # =======================================================================
    # MFFU RAPID EOD 50K -- identical but the funded trail is END-OF-DAY.
    # help.myfundedfutures.com/en/articles/16158363-rapid-eod-50k-a-comprehensive-look
    # =======================================================================
    FirmRules(
        name="MFFU Rapid EOD 50K",
        start_balance=50_000,
        fee_eval=157.0, fee_is_monthly=True, fee_activation=0.0, fee_reset=157.0,

        eval_target=3_000, eval_mll=2_000,
        eval_mll_type=EOD_TRAIL, eval_trail_cap=100,
        eval_daily_loss=None, eval_min_days=4, eval_consistency_pct=0.30,

        funded_mll=2_000,
        funded_mll_type=EOD_TRAIL, funded_trail_cap=100,
        funded_daily_loss=None,
        breach_on_unrealized=False,         # EOD: only the closed balance can breach
        profit_split=0.90,

        payout_min_profit=2_100,
        payout_min_days=1, payout_period_days=1,
        payout_min_amount=500.0, payout_max_amount=None,
        payout_keep_buffer=2_100.0,         # must be ABOVE buffer to request AND remain
        payout_cycle_profit=500.0,          # "subsequent cycles: $500 net since last payout"
        benchmark_days_required=0, benchmark_day_profit=0.0,
        max_payouts=None,
        withdraw_moves_threshold=False,
        consistency_pct=None,
        max_contracts=3,

        source="help.myfundedfutures.com Rapid EOD 50k (official), fetched 2026-08-20",
        unverified=(
            "buffer modelled as must-remain, per Igor",
            "price not stated on the article; assumed equal to Rapid $157/mo -- if the EOD "
            "variant costs more, its EV is overstated here",
            "'limited-time offer' per proptradingvibes -- may not be purchasable",
            "7-day inactivity rule not modelled (a coinflip campaign trades daily)",
        ),
    ),

    # =======================================================================
    # LUCIDDAILY 50K -- eval drawdown is a CHECKOUT TOGGLE. Funded is always intraday.
    # Prices are the VIBES-code (40% off) figures; list prices in unverified.
    # =======================================================================
    FirmRules(
        name="LucidDaily 50K int+DLL",
        start_balance=50_000,
        fee_eval=81.60, fee_activation=0.0, fee_reset=81.60,
        eval_target=3_000, eval_mll=2_000,
        eval_mll_type=INTRADAY_TRAIL, eval_trail_cap=100,
        eval_daily_loss=1_200, eval_min_days=0, eval_consistency_pct=0.50,
        funded_mll=2_000, funded_mll_type=INTRADAY_TRAIL, funded_trail_cap=100,
        funded_daily_loss=None,
        breach_on_unrealized=True,
        profit_split=0.90,
        payout_min_profit=2_100, payout_min_days=0, payout_period_days=1,
        payout_min_amount=500.0, payout_max_amount=None,
        payout_keep_buffer=2_100,           # Lucid states the buffer is NON-WITHDRAWABLE
        payout_cycle_profit=0.0,
        benchmark_days_required=0, benchmark_day_profit=0.0,
        max_payouts=None, withdraw_moves_threshold=False, consistency_pct=None,
        max_contracts=4,
        source="phidias/proptradingvibes LucidDaily writeups, fetched 2026-08-20",
        unverified=("no OFFICIAL Lucid help-centre page retrieved -- both sources are "
                    "third-party affiliate guides. Weakest provenance in this file.",
                    "list price $136; $81.60 assumes the VIBES 40% code holds",
                    "sim profit payout capped at $15,000 total at live transition -- "
                    "not modelled (a coinflip account dies far below this)",
                    "red-folder news = HARD breach that ends the account; not modelled"),
    ),

    FirmRules(
        name="LucidDaily 50K EOD+DLL",
        start_balance=50_000,
        fee_eval=99.0, fee_activation=0.0, fee_reset=99.0,
        eval_target=3_000, eval_mll=2_000,
        eval_mll_type=EOD_TRAIL, eval_trail_cap=100,
        eval_daily_loss=1_200, eval_min_days=0, eval_consistency_pct=0.50,
        funded_mll=2_000, funded_mll_type=INTRADAY_TRAIL, funded_trail_cap=100,
        funded_daily_loss=None,
        breach_on_unrealized=True,          # funded is intraday regardless of the toggle
        profit_split=0.90,
        payout_min_profit=2_100, payout_min_days=0, payout_period_days=1,
        payout_min_amount=500.0, payout_max_amount=None,
        payout_keep_buffer=2_100, payout_cycle_profit=0.0,
        benchmark_days_required=0, benchmark_day_profit=0.0,
        max_payouts=None, withdraw_moves_threshold=False, consistency_pct=None,
        max_contracts=4,
        source="phidias/proptradingvibes LucidDaily writeups, fetched 2026-08-20",
        unverified=("as above; list $165, VIBES $99",
                    "the toggle changes ONLY the eval trail -- funded is intraday in all "
                    "four configurations, so the premium buys eval survival only"),
    ),

    FirmRules(
        name="LucidDaily 50K EOD noDLL",
        start_balance=50_000,
        fee_eval=111.0, fee_activation=0.0, fee_reset=111.0,
        eval_target=3_000, eval_mll=2_000,
        eval_mll_type=EOD_TRAIL, eval_trail_cap=100,
        eval_daily_loss=None, eval_min_days=0, eval_consistency_pct=0.50,
        funded_mll=2_000, funded_mll_type=INTRADAY_TRAIL, funded_trail_cap=100,
        funded_daily_loss=None,
        breach_on_unrealized=True,
        profit_split=0.90,
        payout_min_profit=2_100, payout_min_days=0, payout_period_days=1,
        payout_min_amount=500.0, payout_max_amount=None,
        payout_keep_buffer=2_100, payout_cycle_profit=0.0,
        benchmark_days_required=0, benchmark_day_profit=0.0,
        max_payouts=None, withdraw_moves_threshold=False, consistency_pct=None,
        max_contracts=4,
        source="phidias/proptradingvibes LucidDaily writeups, fetched 2026-08-20",
        unverified=("as above; list $185, VIBES $111 -- the most expensive config",),
    ),

    # =======================================================================
    # TRADEIFY SELECT DAILY 50K -- EOD trail at BOTH stages. Refreshed 2026-08-20.
    # =======================================================================
    FirmRules(
        name="Tradeify Select Daily 50K",
        start_balance=50_000,
        fee_eval=165.0, fee_activation=0.0, fee_reset=95.0,
        eval_target=3_000, eval_mll=2_000,
        eval_mll_type=EOD_TRAIL, eval_trail_cap=100,
        eval_daily_loss=None, eval_min_days=3, eval_consistency_pct=0.40,
        funded_mll=2_000, funded_mll_type=EOD_TRAIL, funded_trail_cap=100,
        funded_daily_loss=1_000, daily_loss_is_soft=True,
        breach_on_unrealized=False,
        profit_split=0.90,
        payout_min_profit=2_100, payout_min_days=0, payout_period_days=1,
        payout_min_amount=250.0, payout_max_amount=1_000.0,
        payout_keep_buffer=2_100,           # "$2,100 must remain in account"
        payout_max_mult_cycle=2.0,          # "up to 2x profit since last payout"
        payout_cycle_profit=0.0,
        benchmark_days_required=0, benchmark_day_profit=0.0,
        max_payouts=None, withdraw_moves_threshold=False, consistency_pct=None,
        max_contracts=4,
        source="propdatalab.com/firms/tradeify (help.tradeify.co 403'd), 2026-08-20",
        unverified=("official help centre refused automated fetch; numbers are from a "
                    "third-party aggregator and differ from the 2026-07-20 pull",
                    "breach_on_unrealized: Tradeify's own pages contradict each other "
                    "(drawdown article says EOD closed balance, Essential Rules says "
                    "peak NetLiq incl. unrealized). Modelled False -- the generous side.",
                    "microscalping rule: >50% of trades AND >50% of profit must be held "
                    ">10s. A tight-bracket coinflip plausibly violates this. NOT modelled."),
    ),

    # =======================================================================
    # TAKE PROFIT TRADER 50K -- EOD eval, then PRO flips to INTRADAY. 80/20.
    # =======================================================================
    FirmRules(
        name="TakeProfitTrader 50K PRO",
        start_balance=50_000,
        fee_eval=180.0, fee_is_monthly=True, fee_activation=130.0, fee_reset=180.0,
        eval_target=3_000, eval_mll=2_000,
        eval_mll_type=EOD_TRAIL, eval_trail_cap=0,
        eval_daily_loss=None, eval_min_days=5, eval_consistency_pct=0.50,
        funded_mll=2_000, funded_mll_type=INTRADAY_TRAIL, funded_trail_cap=0,
        funded_daily_loss=None,
        breach_on_unrealized=True,
        profit_split=0.80,
        payout_min_profit=2_000,            # "build profit equal to max drawdown"
        payout_min_days=0, payout_period_days=1,
        payout_min_amount=250.0, payout_max_amount=None,
        payout_keep_buffer=2_000.0,         # buffer == max drawdown; must remain
        payout_cycle_profit=0.0,
        benchmark_days_required=0, benchmark_day_profit=0.0,
        max_payouts=None, withdraw_moves_threshold=False, consistency_pct=None,
        max_contracts=6,
        source="tradecovex.com Take Profit Trader Rules 2026, fetched 2026-08-20",
        unverified=("no official TPT help page retrieved",
                    "trail_cap=0 (trails to the starting balance then stops) NOT confirmed; "
                    "if TPT's trail never freezes the EV here is overstated",
                    "inside the buffer zone the split DROPS TO 50% if the account has been "
                    "active <60 trading days -- a coinflip account is always inside that "
                    "window, so the effective split is probably 0.50 not 0.80. Swept.",
                    "$130 activation is paid ON PASSING and IS modelled",
                    "reset $399-$1,499 -- far above fee_eval; modelled as monthly rebill"),
    ),
]
