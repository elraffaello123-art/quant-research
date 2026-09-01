# The Kalshi pricing wedge is the spread

Replication and honest-cost audit of Yang (2026), *Pricing Prediction Markets: Incomplete
Markets, Selection Rules, and Risk Premia* (SSRN 6468338).

**Result: the wedge replicates in structure, is worth about one cent at the mid, and is
strongly negative at any price a taker could actually transact.** The positive λ that the
paper measures lives entirely inside the bid-ask spread.

Code: `pm/kalshi_fetch.py` (collector), `pm/wedge.py` (estimation).
Sample: 17,671 settled Kalshi contracts, all 2026, volume ≥ 100, stratified random sample of a
486,929-contract universe.

---

## 1. What the paper claims

A one-parameter pricing-measure selection rule, the Wang transform:

```
p_mkt = Φ( Φ⁻¹(p*) + λ )
```

λ > 0 means quoted prices sit **above** physical probabilities. Estimated by MLE on resolved
contracts. Headline: λ = 0.178 on Kalshi (N = 199,671), λ = 0.172 for 2026 alone
(N = 169,072). The cross-section is economically clean — the wedge is larger where volume is
lower (`ln Volume` = −0.057), larger for longer-dated contracts (`ln Duration` = +0.109), and
decays over contract life with a half-life of 33% of lifetime.

The paper estimates λ on hourly **mid** prices.

## 2. Why that matters

A mid is not a price. Kalshi's public candlestick endpoint returns `yes_bid` and `yes_ask`
alongside the trade price, so λ can be re-estimated at the price a taker could actually have
hit. The wedge says the quoted side is overpriced, so the strategy **sells** it — and selling
means receiving that side's **bid**, not the midpoint.

Two hypotheses make opposite predictions about the same number:

- **Mispricing**: λ survives at the executable price, net of fees. There is a taker edge.
- **Risk premium**: λ dies between mid and executable, because it *is* the spread — what
  makers are paid for quoting a wide book on a thin contract.

This cannot be settled by algebra, because the wedge is largest exactly where spreads are
widest. The two effects fight each other.

## 3. The headline numbers

Median spread across the sample is **7.9c** (mean 30.2c, p90 91c).

| Estimator | λ | SE | t | N |
| --- | --- | --- | --- | --- |
| Directional, mid (paper's spec) | +0.0255 | 0.0103 | +2.48 | 17,671 |
| Complement-invariant, mid | **+0.0356** | 0.0103 | +3.45 | 17,671 |
| Complement-invariant, **executable** | **−0.4413** | 0.0112 | −39.34 | 14,393 |

Always report the complement-invariant number. The Wang transform is not framing-invariant —
relabelling YES as NO sends λ to −λ — and exchanges enforce YES + NO = 1, so a directional
estimate can pick up pure labelling asymmetry. This is the check that collapsed the paper's
own Polymarket estimate from 0.165 to 0.049.

### The spread cut is the mechanism

| Spread bucket | λ at mid | λ at executable | N |
| --- | --- | --- | --- |
| tight ≤ 2c | −0.060 * | −0.081 ** | 3,088 |
| 2–10c | −0.031 | −0.113 *** | 6,794 |
| wide > 10c | **+0.114** *** | **−1.007** *** | 7,789 |

Where the book is tight there is **no positive wedge at all** — it is slightly negative. The
entire positive λ lives in books wider than 10 cents, and inverts violently when priced at the
bid.

The category table makes the same point without needing an argument. λ tracks spread almost
mechanically:

| Category | median spread | λ (CI, mid) |
| --- | --- | --- |
| Elections | 2c | −0.055 |
| Climate and Weather | 3c | +0.008 |
| Commodities | 3c | +0.006 |
| Financials | 6c | −0.078 |
| Sports | 8c | +0.032 |
| Economics | 10c | +0.248 * |
| Mentions | 17c | +0.052 |
| Entertainment | 18c | +0.460 *** |

### What it is worth in cents

| Quoted | edge @ mid | edge @ executable | fee | net |
| --- | --- | --- | --- | --- |
| 0.05 | +0.36c | −6.44c | 1.00c | **−7.44c** |
| 0.10 | +0.61c | −10.04c | 1.00c | **−11.04c** |
| 0.20 | +0.98c | −14.45c | 2.00c | **−16.45c** |
| 0.35 | +1.31c | −17.23c | 2.00c | **−19.23c** |
| 0.50 | +1.42c | −17.05c | 2.00c | **−19.05c** |

Selling the longshot at the executable bid loses 6–17 cents per contract before fees, at every
price level. **There is no taker edge.**

## 4. What replicates and what does not

**The volume effect is real and is not a spread artifact.** This is the finding worth keeping.

| Volume tercile | median spread | λ (CI, mid) |
| --- | --- | --- |
| low | 8c | **+0.181** *** |
| mid | 8c | +0.038 * |
| high | 7c | **−0.094** *** |

Monotone across terciles whose median spreads are nearly identical. Thin markets really do
price differently, beyond the mechanical effect of their wider quotes.

**The duration effect does not survive as an independent effect.**

| Duration tercile | median spread | λ (CI, mid) |
| --- | --- | --- |
| low | 4c | −0.053 ** |
| mid | 6c | +0.045 * |
| high | **18c** | +0.120 *** |

This looks like a clean replication of `ln(Duration)` = +0.109 until you read the spread
column. Long-dated contracts have wide books; the duration coefficient and the spread are the
same fact wearing two hats. Same failure mode as an options greek that turns out to be 73%
spot by R².

## 5. Robustness

- **Event-clustered bootstrap** (300 draws, resampling whole events — contracts on one game or
  one strike ladder are not independent): SE = 0.0108 against a naive 0.0103, t = 3.30. The
  headline survives clustering.
- **Leave-largest-series-out**: λ ranges 0.033–0.048 dropping each of the four biggest series.
  Not carried by one series.
- **Sports vs non-sports**: mid +0.032 vs +0.063; executable −0.468 vs −0.234. Both positive at
  the mid, both strongly negative at the executable price. The result is not a sports artifact,
  though the sample is 87% sports by count.
- **Selection note, and it cuts the safe way**: the executable estimate drops contracts whose
  folded bid falls below 2c. Those are the *worst* trades, so dropping them biases λ_exec
  toward zero. The true picture is worse than −0.44, not better.

## 6. An unreconciled discrepancy with the paper

**I do not reproduce the paper's level.** Its 2026 Kalshi estimate is λ = 0.172 on N = 169,072
— the same year as this sample. I get 0.025–0.048 across every variant tried:

| Variant | λ |
| --- | --- |
| Directional, mid, p ∈ (0.02, 0.98) | +0.0254 |
| Directional, mid, p ∈ (0.05, 0.95) — the paper's Table 19 filter | +0.0299 |
| Directional, last trade price | +0.0472 |
| Complement-invariant, mid | +0.0356 |
| Complement-invariant, last trade price | −0.0074 |

A 4–7× gap, unexplained.

**Hypothesis tested and rejected.** The paper excludes "pure randomness markets" explicitly in
its *Polymarket* section; for Kalshi it states only volume ≥ 100 and a price filter. Those
auto-generated crypto and commodity shards are ~87% of Kalshi's settled tickers by count, and I
excluded them. If they carried a large wedge, that would reconcile everything.

They do not. On 2,207 randomness contracts fetched at minute resolution: λ_CI at mid = **+0.041**
(SE 0.028, t = 1.47, not significant), λ_CI executable = −0.037. Statistically
indistinguishable from the main sample. Their median spread is **2c** — crypto shards are the
tightest books on the venue — and, exactly as the spread story predicts, they are the one
subsample where the executable estimate is *not* negative (+0.045 in the tight-spread bucket).

Remaining candidates, none tested:

1. My universe is built by enumerating currently-listed series, so series delisted before the
   collection date are missing. The paper's "historical API tier" may reach them.
2. My 2026 universe is 486,929 contracts against the paper's 169,072, so its inclusion rule is
   materially stricter than volume ≥ 100 in some way not stated.
3. A different opening-price definition or price field.

This is worth raising with the author. Note it does not affect the audit's conclusion: the
executable-price result is computed on the same contracts as the mid-price result, so the
mid-to-executable collapse holds regardless of which sample's level is right.

## 7. Conclusion

The wedge is real, replicates the paper's volume cross-section, and is **entirely inside the
spread**. It is a risk premium paid to makers for bearing inventory and adverse-selection risk
in thin markets, not a mispricing available to a taker — which is what the paper's own title
says, and what its Manifold play-money sign reversal already implied.

The practical reading: **"avoid the markets the quant shops make" is correct as a description
of where λ lives, and useless as a trading instruction**, because the reason λ lives there is
that nobody wants to quote those books. You get paid the wedge only by becoming the maker who
bears the risk — the same conclusion reached independently on Polymarket's liquidity-rewards
programme, where the safe markets were competed and the uncompeted ones were uncompeted because
they were dangerous.

---

## CORRECTION (2026-09-01): the positive mid-price wedge is an empty-book artifact

The panel above admitted any quote that was not the fully degenerate 0.00/1.00.
That let through books quoted **0.02 / 0.98** — no bid, no offer, a placeholder
spread of 96 cents. Those are not books, and they carry the entire positive wedge.

Restricted to genuinely two-sided quotes (bid > 0 and ask < 1), λ by book quality:

| Book quality | N | λ at mid | λ at executable |
| --- | --- | --- | --- |
| spread ≤ 2c | 2,605 | −0.023 (t −0.81) | −0.047 (t −1.62) |
| spread ≤ 5c | 6,723 | −0.036 (t −2.07) | −0.081 (t −4.55) |
| spread ≤ 10c | 9,137 | −0.024 (t −1.59) | −0.093 (t −6.12) |
| **spread > 10c** | 7,312 | **+0.109 (t +7.18)** | **−1.005 (t −55.97)** |

**Where a real book exists there is no positive pricing wedge at the mid at all** —
it is zero to slightly negative. The headline +0.036 was a weighted average of a
null on tradeable books and a large positive number on quotes nobody could trade.

This strengthens the conclusion rather than weakening it. The earlier framing was
"the wedge is inside the spread." The accurate framing is stronger: **the wedge is
an artifact of taking the midpoint of quotes that are not a market.**

## Can you buy the favourite side?

Tested because it is the natural next thought: if longshots are overpriced then
favourites are underpriced, so buy the 91c and 99c contracts. Buying the favourite
and selling the longshot are the same position (YES + NO = 1), so this is the same
question asked from the other end. Code: `pm/favourites.py`.

**The fee settles the 99c case before any data is involved.** Kalshi charges
`0.07·C·p·(1−p)` **rounded up to the cent**:

| Price | raw fee | charged | total cost | max profit | breakeven win% |
| --- | --- | --- | --- | --- | --- |
| 0.90 | 0.630c | 1.00c | 91.00c | +9.00c | 91.00% |
| 0.95 | 0.333c | 1.00c | 96.00c | +4.00c | 96.00% |
| 0.98 | 0.137c | 1.00c | 99.00c | +1.00c | 99.00% |
| **0.99** | 0.069c | **1.00c** | **100.00c** | **0.00c** | **100.00%** |

At 0.99 the raw fee is 0.07c and the charge is a full cent, so total cost is exactly
$1.00 — the contract's maximum payoff. **Maximum profit is zero with 99c at risk.**
Buying 99c contracts on Kalshi is strictly −EV regardless of how good the probability
estimate is. That is arithmetic, not a forecasting question.

And the data agrees at every band (tight books, spread ≤ 5c):

| Ask band | N | win% | mean ask | gross | fee | net |
| --- | --- | --- | --- | --- | --- | --- |
| 0.80–0.85 | 133 | 83.46% | 82.39c | +1.07c | 1.47c | −0.40c |
| 0.85–0.90 | 131 | 83.97% | 86.94c | −2.97c | 1.00c | −3.97c |
| 0.90–0.93 | 86 | 88.37% | 91.15c | −2.78c | 1.00c | −3.78c |
| 0.93–0.96 | 79 | 89.87% | 94.09c | −4.22c | 1.00c | −5.22c |
| 0.96–0.98 | 58 | 91.38% | 96.71c | −5.33c | 1.00c | −6.33c |
| 0.98–1.00 | 79 | 97.47% | 98.65c | −1.18c | 1.00c | −2.18c |

Favourites are slightly **over**priced at the ask, not underpriced. A 91c contract
resolves yes 88.4% of the time. Sample sizes per band are small (58–133) and these
are not precise estimates, but nothing is positive and the fee alone exceeds any
plausible edge above 0.95.

## Testing Lee, Lee & Lee (2026) — "systematic underconfidence"

SSRN 6748186 studies 113,338 BTC/ETH contracts as digital options and reports a
positive variance risk premium and systematic underconfidence: prices pulled toward
0.50, so favourites should be underpriced. It uses **trade VWAP** and contains zero
occurrences of "bid", "ask", "bid-ask", "transaction cost", or "execution".

Its claim **replicates at the mid** on the crypto contracts, which are the tightest
books on Kalshi (2c median spread):

| Mid band | N | win% | mean mid | gross edge |
| --- | --- | --- | --- | --- |
| 0.55–0.75 | 620 | 65.81% | 62.31c | **+3.49c** |
| 0.75–0.95 | 121 | 88.43% | 82.29c | **+6.14c** |

Favourites really are underpriced relative to the midpoint. But the edge is
approximately the half-spread plus the fee. Buying at the ask in the best-populated
band (0.55–0.65, N=464): +1.74c gross, **−0.26c net**. Break-even at best, negative
in every other band.

The pattern is the same as the wedge: a real statistical regularity at the midpoint,
which is exactly consumed by the cost of crossing to reach it. Both papers are
measuring the price of liquidity and calling it a property of beliefs.

## A reliability diagram is a weighting choice, not a fact

Lee, Lee & Lee's Figure 4 shows Kalshi contracts priced near 0.35 resolving yes ~9%
of the time and contracts near 0.65 resolving ~89%. Read literally that is a
**24-cent** edge, which no functioning book could carry.

Their diagrams pool transactions — 35.9M Kalshi trades across 40,874 contracts
(median 131 each), 240.8M Polymarket trades across 72,464 (median 2,032). A contract
with 10,000 trades enters the histogram 10,000 times.

Rebuilding the same diagram from Kalshi quote paths, on 2,184 crypto contracts and
48,280 observations (`pm/calibration.py`):

| Price bin | mean predicted | realized, **observation**-weighted | realized, **contract**-weighted |
| --- | --- | --- | --- |
| 0.2–0.3 | 0.247 | 0.193 | 0.208 |
| 0.3–0.4 | 0.349 | 0.299 | 0.317 |
| 0.4–0.5 | 0.451 | 0.389 | **0.450** |
| 0.5–0.6 | 0.549 | 0.480 | **0.546** |
| 0.6–0.7 | 0.647 | 0.570 | **0.655** |
| 0.7–0.8 | 0.747 | 0.691 | **0.772** |

**Weight each contract once and the book is calibrated to within 0.01 across the
middle of the range.** Weight each observation once and 6–8 percentage points of
apparent miscalibration appear.

The cause is dispersion in path length. Across contracts the median path is 14
observations, p90 is 33, p99 is 162 and the maximum is **858** — so the **top 1% of
contracts supply 17.6% of all pooled observations, and the top 10% supply 42.2%**.
A minority of long-lived contracts dominates the pooled statistic. It is *not* an
asymmetry in which outcome lingers — contracts ending no contribute 1.03× the
observations of contracts ending yes, which is nothing.

Taking one observation per contract at 5% of life gives the same well-calibrated
answer as contract-weighting, with gaps inside ±0.03 in every populated bin.

**Stated precisely:** the artifact demonstrated here has the *opposite sign* to the
paper's curve, and the paper pools trades where this pools quotes. This does not
prove their figure is this artifact. It proves something weaker and still decisive —
a transaction-weighted reliability diagram is not evidence about whether contracts at
a given price are correctly priced, and cannot be read as a 24-cent edge.

The paper's own fee footnote is the tell, and it is honest: implied volatility,
risk-neutral densities and the VRP "are derived from observed transaction prices, not
from trader returns, so fee structures do not affect our results." That is correct,
and it is also the reason none of it is a trading claim.
