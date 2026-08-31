"""
propsim.py — Monte Carlo for prop-firm account structures under a ZERO-EDGE strategy.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
This is NOT `harness.py`. The harness backtests a signal against real bars and tries to
falsify the edge. This file assumes there is NO edge — the trading is a literal coinflip —
and asks a completely different question:

    Given that the trading is worthless, is the ACCOUNT STRUCTURE worth money?

That is a real question. A prop account is a call option: you pay a fixed fee (capped
downside) for a shot at a payout stream. The fee is the premium. Whether that option is
cheap or expensive is decided entirely by the firm's ruleset geometry, not by trading.

THE TWO RESULTS THIS FILE EXISTS TO QUANTIFY
--------------------------------------------
Both are provable analytically for a driftless walk. The Monte Carlo's job is to add the
frictions the math can't carry (min trading days, daily loss limits, consistency rules,
contract discreteness) and to CONFIRM the clean cases. If the sim disagrees with theory
on the clean cases, the sim is broken — that is what `propsim_tests.py` checks.

  1. POSITION SIZE DOES NOT CHANGE PASS PROBABILITY.
     P(hit +T before -D) = D / (D + T) for a driftless walk. Invariant to bet size.
     Sizing only moves cycle TIME, cost drag, and barrier OVERSHOOT. Overshoot is the
     only one that touches EV, and it is strictly a penalty: oversize and you jump past
     the MLL instead of landing on it.

  2. LIFETIME EXTRACTION IS FIXED BY THE MARTINGALE.
     A zero-edge funded account has an absorbing lower barrier and no drift, so it dies
     with probability 1. By optional stopping,
         E[total withdrawn over the account's life] = initial distance to MLL - cost drag
     INDEPENDENT of withdrawal policy. Withdrawing early does not raise EV.

     Withdrawal timing matters only where a rule BREAKS the martingale. There are exactly
     four such places, and they are the whole game:
        - the MLL not moving down when you withdraw (every payout shrinks your buffer)
        - a trailing DD that FREEZES (the barrier stops chasing you — a structural gift)
        - min trading days before payout (you can die with money trapped inside)
        - consistency rules that void a payout you already earned

COSTS
-----
$5/round-turn/contract by default, and that is deliberately NOT zero here even though
`harness.py` runs at zero. Different question: in the harness, cost is noise against an
edge we are trying to detect. Here there IS no edge, so cost is the only drift in the
system. It is still small against a $3k target — the point is to MEASURE it, not argue
about it. `cost_drag` is reported on every result.

Slippage is not modelled as a cost. It enters as a SIZING constraint: see
`max_safe_contracts`, which refuses a size whose worst-case slipped stop would fill
through the MLL.

MODELLING CHOICE THAT IS DELIBERATELY CONSERVATIVE
--------------------------------------------------
Within a trade we sample both the max favourable excursion (MFE) and max adverse
excursion (MAE) from their exact distributions, then apply MFE FIRST and MAE second.
For an intraday-trailing MLL that is the worst case: the peak ratchets the threshold up,
and then the trough is tested against the raised threshold. Real paths sometimes go the
other way. We take the bad ordering on purpose — this sim should not flatter the setup.
"""

from __future__ import annotations   # py3.9: lets `float | None` work in annotations

from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# Instruments. tick_value is dollars per tick per contract.
# ---------------------------------------------------------------------------
INSTRUMENTS = {
    "MNQ": dict(tick_value=0.50, cost_rt=1.00, typical_slip_ticks=1),
    "NQ":  dict(tick_value=5.00, cost_rt=5.00, typical_slip_ticks=1),
    "MES": dict(tick_value=1.25, cost_rt=1.00, typical_slip_ticks=1),
    "ES":  dict(tick_value=12.50, cost_rt=5.00, typical_slip_ticks=1),
}

# MLL types.
STATIC = "static"                  # fixed at start - mll, never moves
EOD_TRAIL = "eod_trailing"         # trails the end-of-day CLOSED balance
INTRADAY_TRAIL = "intraday_trailing"  # trails peak UNREALIZED equity — the dangerous one


@dataclass
class FirmRules:
    """One account type at one size. All money in dollars, all relative to start balance.

    `trail_cap` is the value the trailing threshold stops at, expressed as profit above
    start (so 0.0 = "the trail freezes once it reaches your starting balance", which is
    the common form). None means the trail never freezes and chases you forever.
    """
    name: str
    start_balance: float

    # --- costs to the trader
    fee_eval: float                 # one-time or monthly, see fee_is_monthly
    fee_activation: float = 0.0     # paid on passing, to turn on the funded account
    fee_is_monthly: bool = False
    # Cost to RETRY a failed eval. This is not a detail: you buy the account once and
    # reset it after each failure, so the marginal cost of an attempt is this, not
    # fee_eval. Pricing every attempt at the purchase price overstates the cost of a
    # campaign badly and can flip a +EV account to -EV. Tradeify discounts resets 42%;
    # MFFU does not discount at all. That spread reorders the firms.
    fee_reset: float | None = None   # None = not found; falls back to fee_eval

    # --- eval stage
    eval_target: float = 3000.0
    eval_mll: float = 2000.0
    eval_mll_type: str = EOD_TRAIL
    eval_trail_cap: float | None = 0.0
    eval_daily_loss: float | None = None
    eval_min_days: int = 0
    eval_max_days: int | None = None
    # Consistency DURING the eval: no single day's profit may exceed this fraction of
    # total profit. This is the rule that blocks passing on one big trade — you hit the
    # target and simply cannot claim the pass until the profit is spread out enough.
    # Modelled as "keep trading until compliant", which is the generous reading; some
    # firms instead inflate the target, which is worse.
    eval_consistency_pct: float | None = None

    # --- funded stage
    funded_mll: float = 2000.0
    funded_mll_type: str = EOD_TRAIL
    funded_trail_cap: float | None = 0.0
    funded_daily_loss: float | None = None
    # Almost every firm researched makes the daily loss limit a SOFT breach: positions
    # flatten, the account locks until the next session, but it survives. Only the MLL
    # is a hard breach. Modelling the DLL as fatal would understate every firm that has
    # one, so the default is soft and any hard-breach firm must say so explicitly.
    daily_loss_is_soft: bool = True
    # Is the MLL breach tested against UNREALIZED equity tick-by-tick, or only against
    # the CLOSED balance? This is the highest-leverage uncertain rule in the whole model.
    # Tradeify contradicts itself: the dedicated drawdown article says EOD closed balance,
    # the Essential Rules page says peak NetLiq "including realized and unrealized".
    # True  = a trade that dips and then closes green can still kill you.
    # False = only closed trades can breach.
    # The difference is worth ~10 points of eval pass rate. Do not leave it assumed.
    breach_on_unrealized: bool = True
    profit_split: float = 0.90

    # --- payout rules
    payout_min_profit: float = 0.0      # profit buffer required before first request
    payout_min_days: int = 0            # trading days before first payout
    payout_min_amount: float = 0.0      # smallest request the firm accepts
    payout_max_amount: float | None = None
    payout_period_days: int = 14        # days between payouts after the first
    payout_keep_buffer: float = 0.0     # firm-mandated equity that must remain
    payout_max_pct: float | None = None      # cap as a fraction of accrued profit
    # Tradeify Select Daily's "Daily Continuity Rule": a request may not exceed this
    # multiple of the profit earned SINCE THE LAST PAYOUT. With a 2x multiple you must
    # earn $500 of new profit to pull $1,000 — it rations extraction against fresh
    # profit rather than against the standing balance.
    payout_max_mult_cycle: float | None = None
    payout_cycle_profit: float = 0.0    # NEW profit required since the last payout
    payout_fee_pct: float = 0.0         # processing fee skimmed off each payout
    max_payouts: int | None = None      # account is CONCLUDED after this many
    withdraw_moves_threshold: bool = False   # THE key rule — see module docstring
    consistency_pct: float | None = None     # best day may not exceed this % of profit

    # Benchmark / "winning day" gating: a day counts only if it clears a profit bar.
    # This is the main mechanism that TRAPS money in an account which then dies, and
    # it is the pure EV leak the martingale result cannot see. Every firm researched
    # uses some version of it (5 winning days is near-universal).
    benchmark_day_profit: float = 0.0
    benchmark_days_required: int = 0

    # Probability the firm refuses a payout or terminates the account on a
    # discretionary "prohibited practice" call. This is NOT copied from a rulebook —
    # it is a judgement input, and it is here because three of the four firms
    # researched name this exact strategy in their prohibited-practices docs:
    #   Alpha    — "gambling tendencies or account rolling"; taking "maximum leverage
    #              on a single position" with "no plan, no stop loss"
    #   FundedNext — "account rolling": buying multiple challenges "to rapidly progress
    #              through probability rather than skill"; "account flipping"
    #   MFFU     — "exploiting the lack of slippage… tight brackets"; Terms demand
    #              "consistency in position sizing, trade frequency, and risk exposure"
    #   Tradeify — weakest: max contract size and DCA "discouraged", not prohibited
    # Modelling this at 0.0 asserts the clauses are never enforced. They exist to be
    # enforced at exactly the moment a payout is claimed, so it is swept, not assumed.
    p_payout_denied: float = 0.0

    # Does the PLATFORM auto-flatten at the loss limit? Every futures prop firm's risk
    # engine does: when equity touches the threshold the position is closed, so a losing
    # trade cannot cost more than the distance from equity to the floor. Added 2026-08-20
    # after this was found manufacturing EV out of nothing.
    #
    # With this False (the historical behaviour) a $1,900 stop taken from $200 above a
    # locked floor books the whole $1,900, driving equity $1,700 BELOW a floor the trader
    # would have been liquidated at. Because E[withdrawn] = -E[equity at death], that
    # phantom overshoot is credited to the trader as profit. It is the single biggest
    # source of fake EV in a max-size policy, and it grows with position size -- so it
    # rewards exactly the "risk it all" strategy that ought to be punished.
    liquidate_at_floor: bool = True

    # --- sizing
    max_contracts: int = 10

    # --- provenance. Anything unverified must say so.
    source: str = ""
    unverified: tuple = field(default_factory=tuple)


@dataclass
class Policy:
    """How the trader behaves. This is what we optimise over."""
    rr: float = 1.0                 # reward:risk. 1.0, 2.0, 3.0
    risk_per_trade: float = 500.0   # dollars risked per trade IN THE EVAL
    # The funded stage is a DIFFERENT problem and wants a different size. The eval is
    # "touch +T before -D", where size does not change the odds, so you size up purely
    # for speed. The funded stage is "stay alive long enough to bank N winning days",
    # where size is the whole survival question. Carrying eval size into the funded
    # account kills ~90% of passed accounts before they can withdraw anything.
    funded_risk_per_trade: float | None = None   # None = reuse risk_per_trade
    stop_ticks: int = 40            # bracket width; with risk_per_trade this fixes size
    trades_per_day: int = 4
    # Trade COUNT per session is a first-class policy variable in the funded stage,
    # not a detail. A "benchmark day" needs one session closing above a profit bar.
    # With 1 trade/day sized above that bar, a benchmark day is a single coinflip (50%).
    # With 4 trades/day you need 3-of-4 (~31%), so you need far more sessions AND you
    # accumulate far more variance against the MLL to bank the same 5 days.
    funded_trades_per_day: int | None = None    # None = reuse trades_per_day
    # funded-stage withdrawal behaviour
    first_payout_at: float = 0.0    # profit level that triggers the first request
    keep_buffer: float = 0.0        # profit left in the account after each withdrawal
    max_days: int = 90              # funded-stage horizon before the account is stale
    eval_days_cap: int = 15         # Igor's constraint: one cycle is 2-3 weeks, not months
    # Once the eval target is reached but the pass is BLOCKED (minimum trading days not
    # yet served, or an eval consistency rule not yet satisfied), a competent trader does
    # not keep firing full size — they coast at token size to burn the day counter without
    # risking the profit. Modelling full size through that window understates every firm
    # with a minimum-trading-day rule.
    coast_risk: float = 20.0
    # Absolute uplift to the win rate over the zero-EV baseline of 1/(1+rr). 0.0 is the
    # pure coinflip. This exists to answer the only question left once the structure is
    # priced: how much real edge does it take to make the account +EV?
    edge: float = 0.0
    # Stop trading for the session once the day is up this much. This is the single most
    # important lever when a payout needs BOTH a balance and N qualifying days: it converts
    # "make $1,400" into "make $280 on each of 5 days", satisfying both constraints with
    # the same dollars instead of banking the balance and then risking it to farm days.
    # None = trade the full session regardless.
    daily_target: float | None = None


# ---------------------------------------------------------------------------
# Within-trade excursions, sampled EXACTLY (no tick-by-tick walk needed).
#
# For a driftless walk from 0 with barriers at -S (stop) and +T (target):
#
#   P(MFE >= m | trade loses) = S(T-m) / [T(S+m)]        for m in [0, T)
#
# Inverting for u ~ U(0,1) gives the sampler below. The winning-trade MAE is the
# mirror image with S and T swapped. This is exact for a continuous driftless walk,
# which is what a coinflip bracket is.
# ---------------------------------------------------------------------------
def _sample_mfe_given_loss(S, T, u):
    """Max favourable excursion of a trade that ends at the stop."""
    return S * T * (1.0 - u) / (u * T + S)


def _sample_mae_given_win(S, T, u):
    """Max adverse excursion of a trade that ends at the target (mirror of above)."""
    return T * S * (1.0 - u) / (u * S + T)


def max_safe_contracts(rules, stop_ticks, instrument, stage="eval"):
    """Largest size whose worst-case SLIPPED stop still lands inside the MLL.

    This is where slippage matters. Not as an EV drag — as the thing that turns a
    "I stopped out exactly at my limit" into a blown account. Igor's hard rule is the
    account never goes under the MLL, so the sizing must respect the slipped fill,
    not the intended fill.
    """
    inst = INSTRUMENTS[instrument]
    mll = rules.eval_mll if stage == "eval" else rules.funded_mll
    worst_ticks = stop_ticks + inst["typical_slip_ticks"]
    per_contract = worst_ticks * inst["tick_value"]
    return max(1, int(mll // per_contract))


class MLLTracker:
    """The threshold. This is the single most error-prone object in the file, which is
    why it is separated out and tested on its own in `propsim_tests.py`.

    Everything is in dollars of profit relative to the starting balance, so the account
    starts at 0.0 and the threshold starts at -mll.
    """

    def __init__(self, mll, mll_type, trail_cap):
        self.mll = mll
        self.type = mll_type
        self.cap = trail_cap
        self.threshold = -mll
        self.peak = 0.0

    def on_equity(self, equity):
        """Called on every equity mark, including unrealized. Only the intraday-trailing
        variant reacts here — that is exactly what makes it more dangerous."""
        if equity > self.peak:
            self.peak = equity
        if self.type == INTRADAY_TRAIL:
            self._ratchet(self.peak)

    def on_day_close(self, closed_balance):
        """Called at each session close with the CLOSED balance."""
        if self.type == EOD_TRAIL:
            self._ratchet(closed_balance)

    def _ratchet(self, high_water):
        new = high_water - self.mll
        if self.cap is not None:
            new = min(new, self.cap)          # the freeze
        if new > self.threshold:
            self.threshold = new

    def on_withdrawal(self, amount, moves):
        """If the firm drops the threshold with the withdrawal, the buffer is preserved
        and payouts are EV-neutral. If it does not, every payout permanently shrinks the
        distance to death. That single boolean is worth more than any sizing decision."""
        if moves:
            self.threshold -= amount

    def breached(self, equity):
        return equity <= self.threshold


# ---------------------------------------------------------------------------
# One account, cradle to grave.
# ---------------------------------------------------------------------------
@dataclass
class AccountResult:
    passed: bool = False
    died: bool = False
    cause: str = ""
    days: int = 0
    trades: int = 0
    withdrawn: float = 0.0      # gross profit taken out, BEFORE profit split
    paid: float = 0.0           # what the trader actually banks, after split
    cost_drag: float = 0.0
    peak_profit: float = 0.0
    n_payouts: int = 0          # how many payouts actually cleared this account's life
    # Per-trade MARKET P&L (the (+T/-S) move, BEFORE commission), cradle to grave.
    # Only populated when simulate_account(..., collect_pnls=True). This is what a live
    # hedge account mirrors: the hedge takes the opposite side of every one of these.
    # Empty by default so the big Monte Carlos pay nothing for it.
    trade_pnls: list = field(default_factory=list)


def _run_stage(rules, pol, inst, stage, rng, withdrawals=False, pnl_sink=None):
    """Trade one stage until an absorbing event. Returns (outcome, result-fields).

    Shared by eval and funded because the mechanics are identical — only the barriers
    and whether withdrawals happen differ.
    """
    is_eval = stage == "eval"
    mll_type = rules.eval_mll_type if is_eval else rules.funded_mll_type
    mll = rules.eval_mll if is_eval else rules.funded_mll
    cap = rules.eval_trail_cap if is_eval else rules.funded_trail_cap
    daily_loss = rules.eval_daily_loss if is_eval else rules.funded_daily_loss
    min_days = rules.eval_min_days if is_eval else 0

    tracker = MLLTracker(mll, mll_type, cap)
    equity = 0.0
    day = 0
    trades = 0
    cost_total = 0.0
    withdrawn = 0.0
    peak = 0.0
    day_profits = []          # for the consistency rule, reset each payout cycle
    last_payout_day = None
    benchmark_days = 0
    n_payouts = 0
    equity_at_last_payout = 0.0

    risk = pol.risk_per_trade
    if not is_eval and pol.funded_risk_per_trade is not None:
        risk = pol.funded_risk_per_trade
    S = risk
    T = risk * pol.rr
    # NOTE: p_win is NOT fixed here. When the platform flattens at the floor, the risk
    # you can actually take is min(S, room-to-floor), and a fair game must price the win
    # probability off THAT, not off the nominal stop. Computing it once from pol.rr hands
    # the trader a free option: downside truncated by the floor, upside probability
    # untouched. At a $100 cushion with a $1,900 stop that is a 27.9% shot at a big win
    # where the true odds are 2%. See the per-trade block below. (Found 2026-08-20.)
    # Contracts implied by the risk and the bracket width. int() floors on purpose:
    # rounding UP would silently risk more than asked and could breach the MLL.
    contracts = max(1, int(risk / (inst["tick_value"] * pol.stop_ticks)))
    cost_per_trade = inst["cost_rt"] * contracts

    # The eval is time-boxed by the trader's own cycle rule, the funded stage is not.
    # An eval that has not passed inside the cycle is a write-off, not a slow winner.
    limit = pol.eval_days_cap if is_eval else pol.max_days
    if is_eval and rules.eval_max_days is not None:
        limit = min(limit, rules.eval_max_days)

    while day < limit:
        day += 1
        day_start = equity
        day_low = equity

        n_trades_today = pol.trades_per_day
        if not is_eval and pol.funded_trades_per_day is not None:
            n_trades_today = pol.funded_trades_per_day

        for _ in range(n_trades_today):
            trades += 1
            u1, u2 = rng.random(), rng.random()

            # Coast mode: target already banked, pass blocked on a day count or a
            # consistency rule. Drop to token size — the goal now is to not give it back.
            if is_eval and equity >= rules.eval_target:
                S, T = pol.coast_risk, pol.coast_risk * pol.rr
            else:
                S, T = risk, risk * pol.rr

            # Conservative ordering: the favourable excursion happens FIRST (ratcheting
            # an intraday trail up), then the adverse excursion is tested against the
            # raised threshold. See module docstring.
            # The risk actually at stake: you cannot lose more than the distance to the
            # floor, because the platform closes you there.
            if rules.liquidate_at_floor:
                S_eff = min(S, max(equity - tracker.threshold, 0.0))
            else:
                S_eff = S
            p_win = (min(S_eff / (S_eff + T) + pol.edge, 0.999)
                     if (S_eff + T) > 0 else 0.0)
            win = u1 < p_win

            if win:
                mfe = T
                mae = _sample_mae_given_win(S_eff, T, u2)
            else:
                mfe = _sample_mfe_given_loss(S_eff, T, u2)
                mae = S_eff

            # ORDER THE TWO EXCURSIONS CHRONOLOGICALLY. Fixed 2026-08-20.
            #
            # A WINNING trade ends by touching +T, so any dip below entry must have
            # happened BEFORE that touch — the trade closes at the target. A LOSING
            # trade ends at -S, so its favourable pop must have come first.
            #
            # The old code applied MFE first in BOTH cases and called it conservative.
            # It is not conservative, it is impossible: it ratchets the trail up off a
            # peak and then tests a trough that occurred before that peak. When a single
            # trade spans from below the payout buffer to above it, the trail jumps to
            # its locked value (+100) and the pre-peak trough — which starts at the
            # entry equity, necessarily below +100 — breaches every single time. That
            # made the "one big funded trade" policy show a 100% death rate and exactly
            # $0 of expected payout on every intraday-trailing account.
            trough = equity - mae
            breach = rules.breach_on_unrealized

            if win:
                # dip first, then the run to target
                if breach and tracker.breached(trough):
                    return "dead", dict(cause="mll", days=day, trades=trades,
                                        cost=cost_total, withdrawn=withdrawn,
                                        peak=peak, n_payouts=n_payouts)
                tracker.on_equity(equity + mfe)
            else:
                # pop first, then the fall to the stop
                tracker.on_equity(equity + mfe)
                if breach and tracker.breached(trough):
                    return "dead", dict(cause="mll", days=day, trades=trades,
                                        cost=cost_total, withdrawn=withdrawn,
                                        peak=peak, n_payouts=n_payouts)
            peak = max(peak, equity + mfe)

            # The platform flattens at the threshold: a loss cannot exceed the distance
            # from current equity down to the floor.
            realised = T if win else -S_eff

            if pnl_sink is not None:
                pnl_sink.append(realised)           # market move only; the hedge mirrors this
            equity += realised - cost_per_trade
            cost_total += cost_per_trade
            day_low = min(day_low, trough)

            # Closed-balance breach test. Always runs: a realised loss that takes the
            # balance through the floor kills the account under either interpretation.
            if not rules.breach_on_unrealized and tracker.breached(equity):
                return "dead", dict(cause="mll", days=day, trades=trades,
                                    cost=cost_total, withdrawn=withdrawn, peak=peak, n_payouts=n_payouts)

            # Day's work done — bank it and walk. Every further trade today risks the
            # cushion for a qualifying day you have already earned.
            if pol.daily_target is not None and (equity - day_start) >= pol.daily_target:
                break

            if daily_loss is not None and (day_start - equity) >= daily_loss:
                if rules.daily_loss_is_soft:
                    break          # locked out for the session; the account survives
                return "dead", dict(cause="daily_loss", days=day, trades=trades,
                                    cost=cost_total, withdrawn=withdrawn, peak=peak, n_payouts=n_payouts)

            if is_eval and equity >= rules.eval_target and day >= min_days:
                # The target is necessary but not sufficient: an eval consistency rule
                # can hold you in the challenge after you've already made the money.
                # `day_profits` holds CLOSED days; today is still open, so include the
                # running day explicitly or a one-day-wonder would slip through.
                if rules.eval_consistency_pct is None:
                    return "passed", dict(cause="", days=day, trades=trades,
                                          cost=cost_total, withdrawn=withdrawn, peak=peak, n_payouts=n_payouts)
                today = equity - day_start
                best = max(day_profits + [today], default=0.0)
                if best <= rules.eval_consistency_pct * equity:
                    return "passed", dict(cause="", days=day, trades=trades,
                                          cost=cost_total, withdrawn=withdrawn, peak=peak, n_payouts=n_payouts)

        tracker.on_day_close(equity)
        day_profits.append(equity - day_start)

        if tracker.breached(equity):
            return "dead", dict(cause="mll", days=day, trades=trades,
                                cost=cost_total, withdrawn=withdrawn, peak=peak, n_payouts=n_payouts)

        # A "benchmark"/"winning" day only counts if it cleared the firm's profit bar.
        # Note this is checked on the day's CLOSED profit, and a day that merely ends
        # green by $1 does not count anywhere researched.
        if (equity - day_start) >= rules.benchmark_day_profit > 0:
            benchmark_days += 1
        elif rules.benchmark_day_profit == 0 and (equity - day_start) > 0:
            benchmark_days += 1

        # ---- funded-stage withdrawals
        if withdrawals:
            capped_out = (rules.max_payouts is not None and
                          n_payouts >= rules.max_payouts)
            eligible = (not capped_out and
                        day >= rules.payout_min_days and
                        benchmark_days >= rules.benchmark_days_required and
                        equity >= rules.payout_min_profit and
                        equity >= pol.first_payout_at and
                        (equity - equity_at_last_payout) >= rules.payout_cycle_profit)
            if last_payout_day is not None:
                eligible = eligible and (day - last_payout_day) >= rules.payout_period_days

            if eligible:
                avail = equity - max(pol.keep_buffer, rules.payout_keep_buffer)
                # Caps stack: an absolute ceiling AND a fraction-of-profit ceiling.
                if rules.payout_max_amount is not None:
                    avail = min(avail, rules.payout_max_amount)
                if rules.payout_max_pct is not None:
                    avail = min(avail, rules.payout_max_pct * max(equity, 0.0))
                if rules.payout_max_mult_cycle is not None:
                    cycle = max(equity - equity_at_last_payout, 0.0)
                    avail = min(avail, rules.payout_max_mult_cycle * cycle)
                # Never withdraw into the threshold. Igor's hard rule: the account
                # cannot go under the MLL under any circumstance, and on every firm
                # researched the threshold does NOT drop when you withdraw.
                avail = min(avail, max(equity - tracker.threshold - 1.0, 0.0))

                if avail >= max(rules.payout_min_amount, 1.0):
                    if _consistency_ok(rules, day_profits, equity - equity_at_last_payout):
                        equity -= avail
                        tracker.on_withdrawal(avail, rules.withdraw_moves_threshold)
                        # Discretionary denial: the money leaves the account either
                        # way (it was requested and cleared), but the trader never
                        # receives it. This is the conservative reading and the one
                        # that matters — a denied payout is a total loss of that cash.
                        if rng.random() >= rules.p_payout_denied:
                            withdrawn += avail * (1.0 - rules.payout_fee_pct)
                        n_payouts += 1
                        last_payout_day = day
                        equity_at_last_payout = equity
                        benchmark_days = 0        # every firm resets the day count
                        day_profits = []          # consistency is per-cycle too

    return "timeout", dict(cause="timeout", days=day, trades=trades,
                           cost=cost_total, withdrawn=withdrawn, peak=peak, n_payouts=n_payouts)


def _consistency_ok(rules, day_profits, total_profit):
    """Best winning day must not exceed consistency_pct of total profit."""
    if rules.consistency_pct is None or total_profit <= 0:
        return True
    best = max([d for d in day_profits if d > 0], default=0.0)
    return best <= rules.consistency_pct * total_profit


def simulate_account(rules, pol, instrument, rng, collect_pnls=False):
    """Full lifecycle: buy eval -> pass or die -> funded -> extract until death.

    collect_pnls=True fills res.trade_pnls with every trade's market move (before
    commission), eval and funded concatenated. That is the exact series a live hedge
    account takes the opposite side of.
    """
    inst = INSTRUMENTS[instrument]
    res = AccountResult()
    sink = [] if collect_pnls else None

    outcome, f = _run_stage(rules, pol, inst, "eval", rng, withdrawals=False,
                            pnl_sink=sink)
    res.days += f["days"]
    res.trades += f["trades"]
    res.cost_drag += f["cost"]
    res.peak_profit = f["peak"]

    if outcome != "passed":
        res.died = True
        res.cause = f["cause"]
        if sink is not None:
            res.trade_pnls = sink
        return res

    res.passed = True
    outcome, f = _run_stage(rules, pol, inst, "funded", rng, withdrawals=True,
                            pnl_sink=sink)
    res.days += f["days"]
    res.trades += f["trades"]
    res.cost_drag += f["cost"]
    res.withdrawn = f["withdrawn"]
    res.paid = f["withdrawn"] * rules.profit_split
    res.n_payouts = f["n_payouts"]
    res.died = outcome != "passed"
    res.cause = f["cause"]
    if sink is not None:
        res.trade_pnls = sink
    return res


def account_ev(rules, pol, instrument, n=20000, seed=0):
    """Monte Carlo one (rules, policy, instrument) cell. Returns a summary dict."""
    rng = np.random.default_rng(seed)
    paid = np.zeros(n)
    passed = np.zeros(n, dtype=bool)
    days = np.zeros(n)
    drag = np.zeros(n)

    for k in range(n):
        r = simulate_account(rules, pol, instrument, rng)
        paid[k] = r.paid
        passed[k] = r.passed
        days[k] = r.days
        drag[k] = r.cost_drag

    fee = rules.fee_eval + rules.fee_activation * passed.mean()
    ev = paid.mean() - fee
    weeks = max(days.mean() / 5.0, 1e-9)
    return dict(
        name=rules.name, instrument=instrument, rr=pol.rr,
        risk=pol.risk_per_trade,
        p_pass=passed.mean(),
        p_pass_theory=rules.eval_mll / (rules.eval_mll + rules.eval_target),
        e_paid=paid.mean(),
        fee=fee,
        ev=ev,
        ev_per_week=ev / weeks,
        mean_days=days.mean(),
        cost_drag=drag.mean(),
        n=n,
    )
