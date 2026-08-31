# Minimum-trade coinflip on the daily-payout accounts — corrected EV

*2026-08-20. Rules: `docs/PROPFIRM_RULES_2026-08-20.md`. Code: `scripts/propfirm_daily_accounts.py`,
`propfirm_minimal_trades.py`. Engine: `toolkit/propsim.py` (14/14 self-tests pass).*

## The policy (Igor's)

    EVAL    one trade per day, sized so exactly N wins clear the target, where
            N = ceil(1 / eval_consistency_pct). Nothing else is traded.
    FUNDED  ONE trade. Risk the whole MLL less the $100 floor. Take the payout. Stop.

Minimum trades everywhere. A zero-edge account dies with probability 1, so every extra trade
is another chance to die plus another round-turn of drag, and adds nothing to expectation.
Trade only to satisfy a rule, in the fewest trades that satisfy it.

`N = ceil(1/c)` lands exactly on each firm's minimum-trading-days rule. Not a coincidence —
consistency and min-days are the same constraint written twice.

## TWO ENGINE BUGS FOUND CHASING THIS. Both are now fixed.

**1. Excursion ordering — was HIDING EV.** `propsim` applied max-favourable excursion before
max-adverse on every trade, documented as "deliberately conservative." For a *winning* trade
that is impossible: the trade closes when it touches the target, so any dip below entry must
precede it. The code ratcheted the trailing floor to its locked +$100 off the peak, then
tested a trough from *before* that peak. A funded account starts at equity 0, below +$100, so
**every winner registered as a breach** — 100% death, exactly $0 expected payout on all four
intraday-trailing accounts. Only bites when one trade spans from below the buffer to above it,
which is why small-risk sweeps never exposed it. Now ordered chronologically: dip-then-target
for winners, pop-then-stop for losers.

**2. Free option at the floor — was MANUFACTURING EV.** `p_win` was computed once from the
policy's reward:risk and never from the remaining cushion. At equity +$200 with the floor
locked at +$100 you have $100 of room but a $1,900 nominal stop, and the sim granted a
**27.9%** shot at a $4,900 win where the true fair-game probability is **2%**. Downside
truncated by the platform's auto-flatten, upside probability untouched. Fixing only the loss
size changes nothing — you bank the money before overshooting; the win probability is the half
that matters. Now `S_eff = min(S, equity - threshold)` and `p_win = S_eff / (S_eff + T)`,
gated by the new `FirmRules.liquidate_at_floor` (default **True** — every futures prop risk
engine flattens at the limit).

Verified against a from-scratch re-implementation outside `propsim`: **$2,906 → $1,411** gross,
matching the analytical answer (~$1,410) to the dollar.

## Corrected results — $50K, MNQ, list price and with the discounts these firms run

| account | overshoot | P(pass) | E[paid \| pass] | list | −30% | −40% | −50% |
|---|---|---|---|---|---|---|---|
| LucidDaily EOD+DLL | +3000 | 0.210 | 1230 | 159 | 189 | **199** | 208 |
| LucidDaily EOD noDLL | +3000 | 0.210 | 1230 | 147 | 180 | 191 | 202 |
| MFFU Rapid EOD | +3000 | 0.217 | 1241 | 112 | 159 | **175** | 191 |
| LucidDaily int+DLL | +3000 | 0.175 | 1252 | 137 | 162 | 170 | 178 |
| MFFU Rapid (intraday) | +3000 | 0.208 | 1230 | 98 | 145 | **161** | 177 |
| TakeProfitTrader PRO | +3000 | 0.202 | 1083 | 12 | 66 | 84 | 102 |
| Tradeify Select Daily | +750 | 0.215 | 785 | 3 | 53 | 69 | 86 |

`E[paid|pass]` converges to ~$1,230–1,250 on six of seven — the same geometry, correctly
measured. Tradeify is the outlier at $785 because of its **$1,000 per-cycle payout cap** and
the 2x-profit-since-last-payout rule, which ration extraction; it is the only firm here whose
payout terms actually bite.

## INTRADAY vs EOD — the answer to Igor's question

For **this** policy, it barely matters:

| pair | intraday | EOD | difference |
|---|---|---|---|
| MFFU Rapid vs Rapid EOD (funded trail) | 161 | 175 | **+14** |
| LucidDaily int+DLL vs EOD+DLL (eval trail) | 170 | 199 | **+29** |

EOD is mildly better, worth $14–29 per account. **Intraday drawdown is only punishing when
you hold the account across many sessions** — it ratchets against you every time equity peaks.
A one-trade policy resolves at a barrier immediately, so the trail never gets time to work.
Minimum-trades is precisely the policy that neutralises the intraday/EOD distinction.

Note this REVERSES the earlier "EOD is worth −$46" finding from `propfirm_daily_mc.py`, which
was produced under bug #1 — a bug that penalised only intraday accounts.

Also: LucidDaily's EOD toggle changes the **eval** trail only. Funded is intraday in all four
configurations, so the $17–29 premium buys eval survival, not funded survival. It still prices
out as worth paying here, but for the opposite reason to the one the marketing implies.

## Eval sizing is flat — 2 wins is right and robust

MFFU Rapid, sweeping the number of equal winning days:

| wins | risk/day | room after 1 loss | P(pass) |
|---|---|---|---|
| 2 | 1500 | 500 | 0.203 |
| 3 | 1000 | 1000 | 0.205 |
| 4 | 750 | 1250 | **0.210** |
| 5 | 600 | 1400 | 0.203 |
| 6 | 500 | 1500 | 0.180 |
| 8 | 375 | 1625 | 0.099 |

Flat across 2–5, then it collapses as the target recedes. **P(pass) is ~0.21, not the ~0.30
previously believed** — once the risk exceeds the room left after one loss, the follow-up trade
stops being a coinflip, which is exactly bug #2 and caps the pass rate.

## WHERE THE EDGE ACTUALLY COMES FROM — and why that is the risk

It is not the trading. Once the trail locks at start+$100 and the buffer forces $2,100 to stay
in the account, **every payout restores a full $2,000 cushion of the firm's money.** The account
becomes a repeatable option on $2,000 that you never have to fund. That is the entire edge.

Which is also the problem. A campaign that passes in exactly 2 days and then places one
maximum-size trade before withdrawing is the literal picture these clauses describe:

- **MFFU** — bans "exploiting the lack of slippage… tight brackets"; Terms require "consistency
  in position sizing, trade frequency, and overall risk exposure."
- **Tradeify** — >50% of trades AND >50% of profit must be held longer than 10 seconds.
- **Lucid** — red-folder news is a hard breach.
- **TPT** — split drops to 50% inside the buffer zone under 60 trading days.

Payout denial at 40% off:

| account | p=0 | p=0.10 | p=0.25 | p=0.50 |
|---|---|---|---|---|
| LucidDaily EOD+DLL | 199 | 174 | 139 | 72 |
| MFFU Rapid EOD | 175 | 148 | 108 | 41 |
| MFFU Rapid (intraday) | 161 | 137 | 101 | 35 |
| TakeProfitTrader PRO | 84 | 62 | 30 | −25 |
| Tradeify Select Daily | 69 | 52 | 27 | −15 |

Everything survives a 25% denial rate. At 50% the two weakest go negative. **The EV is real
geometry; whether the firm honours it is the open question, and it is the only variable here
that is not measured but assumed.**

## Still not verified

- MFFU's $157/mo is not on an official page; the Rapid EOD price is assumed equal to Rapid.
- LucidDaily has no official help-centre source retrieved — both sources are affiliate guides.
- Tradeify's help centre 403'd; its numbers come from an aggregator and differ from the
  2026-07-20 pull.
- TPT's trail-freeze point (modelled: freezes at the starting balance) is not confirmed.
- The wide brackets this policy needs — **76 ticks on MFFU Rapid, 127 on Rapid EOD** (3 minis
  makes it worse) — should be sanity-checked against what is actually placeable.
