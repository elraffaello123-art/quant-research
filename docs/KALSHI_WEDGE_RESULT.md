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
