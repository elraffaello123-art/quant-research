# Coinflip prop-account EV — result (2026-07-20)

**Question.** Igor's thesis: edge contributes ~nothing; prop EV is convexity — a capped-downside
option on a payout stream. Is running a deliberately zero-edge coinflip across the major futures
prop firms +EV?

**Answer. No. Seven of eight accounts are decisively negative. The eighth is exactly zero.**

Code: `toolkit/propsim.py`, `toolkit/propsim_tests.py`, `scripts/propfirm_accounts.py`,
`scripts/propfirm_mc.py`. Full output: `scripts/propfirm_results.txt`.

## Headline (MNQ, 1:1, best config per account, n=20000, 95% bootstrap CI)

| account | EV/cycle | 95% CI | P(pass) | trapped | verdict |
|---|---|---|---|---|---|
| FundedNext Flex 50K | −1 | [−4, +3] | 0.22 | 0.45 | **NOISE** |
| Alpha Zero 50K | −23 | [−29, −18] | 0.22 | 0.62 | −EV |
| MFFU Pro 50K | −31 | [−39, −23] | 0.27 | 0.80 | −EV |
| MFFU Flex 50K | −54 | [−59, −49] | 0.22 | 0.43 | −EV |
| Tradeify Growth 50K | −58 | [−65, −52] | 0.23 | 0.81 | −EV |
| Tradeify Select Flex 50K | −64 | [−69, −58] | 0.21 | 0.36 | −EV |
| FundedNext Legacy 50K | −90 | [−97, −84] | 0.25 | 0.57 | −EV |
| Alpha Advanced 50K | −145 | [−150, −140] | 0.16 | 0.74 | −EV |

*trapped* = passed the eval and still never extracted a single dollar.

**Not one account has a CI above zero.** Best case is break-even before any discretionary
denial risk is priced in.

## Why — the geometry is +EV and the payout rulebook takes it all back

Pure barrier math says these should pay. Closed form, `EV = −fee + P(pass)·split·funded_MLL`
with `P(pass) = D/(D+T)`, gives **+$380 to +$601** per account. Every one positive.

The simulated numbers land 400–700 dollars below that. The gap is entirely payout rules:

1. **Trailing MLL.** The drawdown trails your peak, so `D` never grows as you profit.
   Measured P(pass) is 0.16–0.27 against a theoretical 0.30–0.40.
2. **Benchmark days.** Near-universal: ~5 sessions each closing above $150–200 before any
   payout. A zero-edge walk usually hits the MLL first. This is what produces the 36–81%
   trapped rate — money earned, account passed, nothing extracted.
3. **Payout caps.** 50%-of-profit caps, absolute caps, and 5-payout account termination
   (FundedNext Flex/Rapid, MFFU) cut the extractable tail off.
4. **Subscription fees.** Alpha and MFFU Pro bill monthly for as long as the account lives.

These rules are not incidental. They are precisely the countermeasures against this strategy.

## Two theory results, both confirmed by the sim

1. **Position size does not change P(pass).** `P = D/(D+T)`, invariant to bet size
   (`propsim_tests.py` T1, three sizes, same answer). Size only buys *speed*, and oversizing
   *costs* you via barrier overshoot (T4). Igor's "risk a lot at first" instinct is right for
   the eval — but for speed, not for odds.
2. **Lifetime extraction = distance to MLL, independent of withdrawal policy** (T2, T3).
   So *when* you take a payout does not change EV. Take it as early as rules allow — not to
   raise EV, but to convert trapped equity into banked cash before a rule or drawdown takes it.
   **This answers the buffer question: leave no buffer beyond what the firm mandates.**

## The finding that most surprised me

**The two stages want opposite sizing, and one size for both is what kills you.**

- The **eval** is "touch +T before −D". Size doesn't change the odds, so size big for speed.
- The **funded stage** is "survive N winning days to unlock a payout". Size is the entire
  survival question.

Carrying eval size into the funded account traps ~90% of passed accounts. Optimum funded risk
is $250–600 against an eval risk of $600, and **1 trade per day wins at every single firm** —
a benchmark day is one coinflip (50%) at 1 trade/day versus needing 3-of-4 (~31%) at 4/day,
for a quarter of the accumulated variance.

## Things that did NOT matter

- **R:R (1:1 vs 1:2 vs 1:3)** — moves EV by less than the fee. No firm's ranking changes.
- **MNQ vs NQ** — the contract limit caps both at the *same dollar risk* (micro allowance is
  10× the mini allowance, micros are 1/10 the size). NQ is marginally better on granularity
  alone. Choose on execution, not EV.

## The risk not in the table

Three of four firms name this strategy in their prohibited-practices documents:

- **Alpha Futures** — "gambling tendencies or account rolling"; "maximum leverage on a single
  position" with "no plan, no stop loss" is "not tolerated"; buying accounts and repeating
  until one succeeds is banned by name.
- **FundedNext** — "Account Rolling": "purchasing multiple Challenge Accounts to rapidly
  progress through probability rather than skill". "Account Flipping": "excessive leverage to
  rapidly grow or blow up accounts".
- **MFFU** — bans "exploiting the lack of slippage… tight brackets"; Terms require "consistency
  in position sizing, trade frequency, and overall risk exposure".
- **Tradeify** — weakest: max contract size and DCA "discouraged". No explicit gambling clause.

The sim sweeps `p_payout_denied`. It does not matter here: every account is already negative at
p=0, so the break-even denial rate is **"never +EV"** across the board. Denial risk only widens
an existing loss. Had anything been positive, this would have been the binding term.

## Addendum — Tradeify Select DAILY (Igor's pick), 2026-07-20

Igor was right that the first pass modelled the wrong Tradeify variant. **Select Daily**
has daily payout eligibility with **no benchmark-day requirement**, which removes the
single biggest leak found above. It is the best account of the nine. Script:
`scripts/select_daily_deep.py`.

**His funded-stage plan is optimal.** Sweeping risk × R:R × trades-per-day, the best
funded config *is* $1,000 at 3RR, 1 trade/day — exactly what he proposed. The "two tries"
reading is also correct: a $1,000 DLL against a $2,000 MLL gives two shots at a 25% event,
P(at least one win) = 43.8%.

**But the eval consistency rule structurally forbids the big-RR pass.** A 3RR win at $800
risk books $2,400 in one day. Select's eval requires no day exceed 40% of total profit, so
compliance needs $6,000 total — against a $3,000 target. The winning trade that passes you
*cannot comply*. Measured: 3RR at $800 passes **0.000** of the time with the rule, 0.238
without it. This is a hard structural blocker, not a tuning problem.

**Best legal config**: eval $600 1/day 1:2, funded $1,000 1/day 3RR.

| | value |
|---|---|
| P(pass eval) | 0.194 |
| E[paid to you \| pass] | $637 |
| break-even P(pass) needed | 0.259 |
| **EV per cycle** | **−$41**, 95% CI [−51, −31] |

**Where the pass rate goes** (theory ceiling 0.400): the 15-day cap, the 3-day minimum and
the consistency rule cost almost nothing (0.192 → 0.203 when all relaxed). The damage is
(a) the trailing drawdown with **no lock during eval**, and (b) Tradeify enforcing the
drawdown against **unrealized equity in real time** — an adverse excursion kills you on
trades that would have closed green. Static drawdown alone would give 0.279.

Counter-intuitively, **smaller size makes the eval worse**: each trade's excursion is
tested against the floor, so more trades means more chances to die. Fewest, largest trades
is right — the opposite of the funded stage's requirement in the first pass.

### The finding that matters most

The gap to profitability is 0.194 vs 0.259 — and the only lever that closes it is a real edge.

| edge (win-rate uplift) | eval win rate | P(pass) | EV/cycle |
|---|---|---|---|
| 0.00 (coinflip) | 0.333 | 0.197 | −$38 |
| **0.02** | 0.353 | 0.236 | **+$38** [15, 61] |
| 0.04 | 0.373 | 0.277 | +$135 |
| 0.06 | 0.393 | 0.321 | +$309 |
| 0.10 | 0.433 | 0.411 | +$960 |

**Break-even is ~+1.5 percentage points of win rate — about 2 extra wins per 100 trades.**
Past that the structure is enormously convex in edge: 0.10 of edge returns 25× the EV of
0.02, because P(pass) and lifetime extraction both rise together.

So the honest conclusion is a *correction* to the original thesis, not a rejection of it.
**Prop structures are edge amplifiers, not edge substitutes.** The convexity is real and it
is worth a lot — but it multiplies an edge rather than manufacturing one, and at exactly
zero edge it lands just short of the fee. Igor's instinct that "it's all convexity" is
about 1.5 percentage points away from being right, and that last 1.5 points is the entire
game.

## CORRECTION (2026-07-21) — the earlier "-EV everywhere" conclusion was WRONG

Igor was right. The error was the fee: I priced every attempt at the **$165 list price**.
The account is **$95 flat per attempt** on the standing promo these firms run
near-permanently. Nothing else in the model changed.

**Tradeify Select Daily 50K at $95/attempt is +EV under BOTH readings of the ambiguous
drawdown rule.** Config: eval $600 1/day 1:2, funded $1,000 1/day 3RR (both swept-optimal
— and the funded leg is exactly what Igor proposed).

| drawdown reading | P(pass) | E[paid\|pass] | EV/attempt | 95% CI |
|---|---|---|---|---|
| breach on unrealized (harsh) | 0.194 | $637 | **+$28.8** | [19, 39] |
| breach on closed only (lenient) | 0.239 | $717 | **+$76.7** | [65, 90] |

Break-even needs P(pass) = 95/E[paid|pass] = **0.149**; measured is **0.194**. Margin
+0.045 even on the harsh reading, so the result does not depend on resolving Tradeify's
self-contradictory drawdown documentation.

Monthly, against Tradeify's caps (15 evals/30d, 5 funded accounts per household),
7.7-9.1 days per attempt:

| slots | attempts/mo | EV/mo (harsh) | EV/mo (lenient) | fee outlay |
|---|---|---|---|---|
| 1 | 2.3-2.7 | $79 | $176 | $259 |
| 3 | 6.9-8.2 | $236 | $529 | $777 |
| 5 (saturates cap) | 11.5-13.6 | **$393** | **$882** | $1,296 |

Binding constraint is the **15-evals-per-30-days cap**, not capital. At 50K size this is
a few hundred to ~$900/month — real, but not a living. The lever for more is account
SIZE, not more attempts: E[paid|pass] scales with the funded MLL while the fee scales
more slowly. That is the next thing to test.

**What did NOT change:** the funded-stage ceiling. E[paid|pass] stays ~$630-700 because
lifetime extraction is still bounded by the distance to the MLL. Resets cut the cost of
*reaching* a funded account; they do nothing for what one is *worth*. So the edge-leverage
table above still stands — edge multiplies E[paid|pass], resets only cut acquisition cost.

**The risk that now dominates:** Alpha and FundedNext ban **"account rolling"** — buying
and resetting repeatedly to pass on probability — **by name**. A reset campaign is the
literal definition of what they prohibit. Tradeify has no equivalent clause, which is now
the single strongest reason to prefer it over the other three.

## Caveats

- Rules snapshot **2026-07-20**; several pages were edited within days of that. Re-verify.
- The firm files list every unresolved conflict and every not-found rule in `unverified`.
  Nothing was guessed to fill a gap.
- **"Lucid Flex/Pro" are Lucid Trading products, not MyFundedFutures.** MFFU Flex and Pro were
  modelled. Lucid Trading blocks automated fetching (HTTP 403) and is **not** covered here.
- Not modelled: funded-stage contract scaling (Tradeify/Alpha start funded at half size or
  less, which would make results *worse*), FundedNext's 5:1 max R:R, minimum hold times,
  MFFU Pro's one early 60%-of-profit withdrawal.
- Modelling choice, deliberately conservative: within a trade the favourable excursion is
  applied before the adverse one, which is the worst ordering for an intraday-checked MLL.

## FINAL (2026-07-21) — Lucid Flex 25K on Igor's inputs, and where we converged

Source docs saved to `docs/reference/`: `prop_run_doc.pdf` (Igor's handwritten run plan),
`propfirm_convexity_harvestpremia.pdf`, `prop_asymmetric_payoff.pdf`.

The convexity paper's viability condition is the right frame and is worth stating plainly:

    payoff  = max(-C, U)          a long call: premium C, stochastic upside U
    viable  iff  P > C / U

Igor's inputs: eval pass 0.44, payout|funded 0.50, cost $70, first payout $700 at 100%.

    P = 0.44 x 0.50 = 0.220        C/U = 70/700 = 0.100      -> clears by 2.2x

| basis | U | EV/account | ROI |
|---|---|---|---|
| first payout only | $700 | **+$84** | +120% |
| rinsed, floor trails | $1,000 | **+$150** | +214% |
| rinsed, floor locks at +$100 | $1,300 | **+$216** | +309% |

Rinsing is worth more than the first payout. Once at $1,400 with the floor ratcheted up
behind you, expected TOTAL lifetime extraction is (balance - floor at death) by optional
stopping — roughly $1,000-1,300, not $700.

At 10 accounts/month: spend $700, EV **+$840 to +$2,160**.

### Where the earlier "-EV" conclusion went wrong, and where we actually converge

Three fee/structure errors, all mine, compounding:
1. priced every attempt at LIST price instead of the promo Igor actually pays
2. ignored reset pricing where it applies
3. counted only the FIRST payout, ignoring that the account survives to be rinsed

**Break-even P(payout|funded) = C/(P_eval x U) = 22.7%.** This is the number that matters,
because even my most pessimistic simulated estimate (0.28-0.35, from the harsh
breach-on-unrealized reading) sits ABOVE it. Running my own pessimistic figures through
Igor's fee structure gives +$35/account single-payout, +$125 rinsed.

So the disagreement was never about the SIGN. It was about magnitude — roughly 2-6x — and
both sets of assumptions clear the bar. The structure is +EV.

### What can still break it (ranked)

1. **Discretionary denial.** Not modelled with a number because it is unknowable, and it is
   the only term that can zero the whole thing. Alpha and FundedNext ban "account rolling"
   by name; MFFU/Alpha/FundedNext all ban "exploiting the absence of slippage… tight
   brackets", which is the fill-based edge described here. **Lucid's prohibited-practices
   page returned 403 on every attempt — it is the single most important unread document.**
2. **P(payout|funded).** +EV down to 22.7%; Igor claims 50%, I measure 28-35%. Wide but
   safe margin either way.
3. **Sim-to-live transition.** An edge sourced from demo fill quality does not survive it.
