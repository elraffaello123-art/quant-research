# Systematic trading research — falsification first

Most quant portfolios show you a backtest that worked.

This one shows you the machine that kills backtests that didn't, and an honest record of
what it killed. Every number below came out of that machine, and most of them are negative.

That is the point. An edge you cannot falsify is not an edge, it is a story about the past.

---

## The harness

`toolkit/harness.py` is the only way a profit factor reaches the screen in this repo.

```python
import sys; sys.path.insert(0, "toolkit")
from harness import load_bars, audit

bars = load_bars("data/pkl/nq_5m_all.pkl")
v = audit(my_signal, bars, stop=0.0015, target=0.004)
v.report()
```

A signal is `def signal(day, g) -> list[(bar_index, +1/-1)]`, deciding on bar `i` from
`g.iloc[:i+1]` only. The harness fills at bar `i+1`'s **open** — there is no "fill at the
level" — and then runs a falsification battery:

| Check | What it catches |
| --- | --- |
| Next-open fill diff | Lookahead in the **fill** — the classic "entry at the band" fake |
| Level-fill gap | How much of the edge was living inside the touch price |
| Strict signal replay | Lookahead in the **signal** — a peek at a future bar |
| Random-entry placebo | Edge that is really just directional beta |
| Shuffled-level placebo | Edge that is not actually about the level you claim |
| Bootstrap CI | Whether the point estimate means anything |
| Out-of-sample split | Fit vs. found |
| Concentration | Whether 20 trades are carrying the whole result |
| Parameter plateau | A peak of one, i.e. an overfit |

### Two kinds of lookahead need two different traps

Lookahead in the **fill** is caught by next-open fills. Lookahead in the **signal** is caught
only by strict replay. A signal that peeks at a future bar prints a beautiful ~1.7 profit
factor with every fill-based check green. Both traps are on by default.

### The test that makes the other tests mean something

`toolkit/tests.py` is five self-tests, all must pass. Four prove the harness says **no** to
different fakes: a real lookahead artifact, a signal that peeks, pure coin flips, and a
cherry-picked parameter. The fifth proves it still says **yes** to a synthetic edge that is
genuinely there.

**A filter that only ever says no is not a filter, it is a wall.** Test 4 is what makes the
other four worth anything. If you take one idea from this repo, take that one.

---

## The graveyard

Honest results, most of them negative, all reproducible from `scripts/`.

| Idea | Verdict | The number that killed it |
| --- | --- | --- |
| NQ intraday MR band-fade | **Dead** | PF **1.74 → 1.02** once entries filled at the next open |
| Gamma walls / 0DTE pin | **Dead** | All ≈1.0 honest. Deeper cause below |
| QQQ skew → NQ prediction | **Dead** | Decile spreads 0.2–1.4 bps; one NQ tick is **1.25 bps**. Whole effect is one tick, and the sign was backwards |
| ML meta-labelling, metals ORB | **Dead** | OOS AUC **0.473–0.530**. Best PF 1.274, but the shuffled-label null had median 1.166 → **p = 0.155** |
| Order-book imbalance | **Dead** | Decays sub-second; nothing survives to the next bar's open |
| Metals/oil vol scan (312 pre-registered cells) | **Dead** | Best real PF lost to the random-entry max-null, **p = 0.92** |
| HarvestPremia ORB templates 1/2/3 | **Dead** | Variance claims true, directional claims not |
| Polymarket maker subsidy | **Real but small** | ≈$50–60/day trustworthy core, hard-capped by pool size, and crowded |
| Prop-firm coinflip EV | **Negative** | 8 account types modelled; 7 clearly −EV, best is zero |

### Why the options thread really died

This is the finding I am most pleased with, because it replaced "the edge decayed" with a
measurement. Per-day regression of each QQQ 5-min greek on spot and spot², median R²:

| Column | R² on spot | Reading |
| --- | --- | --- |
| `net_gex` | **0.73** | 73% price wearing an options costume |
| `tilt` | **0.70** | same |
| `skew` | **0.16** | genuinely independent intraday information |

The walls and pin strategies were built on `net_gex` and `tilt`. They were never a second
source of information — they were a noisy copy of the thing they were supposed to predict.

**The rule that came out of it:** before building on any options column, regress it on spot
per day. High R² means it is not a second source, and any cross-source claim for it is false.
Independence is necessary, not sufficient — `skew` cleared this bar and then failed to predict
anything anyway.

---

## Three methodology notes that cost me real money to learn

**1. The null must destroy only the thing you claim is the edge.**
A shuffled-**label** permutation test correctly killed the ORB meta-labelling. Applied to a
prediction market it returned a null with median **+100% return per dollar**. Why: in a
prediction market the price *is* a calibrated probability, so bets at 0.05 win ~5% of the
time. Shuffle the outcomes and they win 50%, and every longshot becomes hugely +EV. The null
was measuring the destruction of the book's calibration, not the absence of an edge. The
correct null shuffles the **signal** and leaves prices, outcomes and sizes fixed. Rebuilt that
way it centred at −0.01 and the real result stood at +0.183, p = 0.005.

**2. Significance is blind to concentration.** The same strategy that passed at p = 0.005 had
20 of 7,517 bets producing 67% of the profit. A permutation test will never tell you that.
Run concentration separately, always.

**3. Statistical significance is not tradeability.** In the hourly crypto work the signal was
still significant at p = 0.005 with a 10-second delay — and worth +0.011 per dollar, which is
nothing. Half-life was 2–3 seconds. Those are two different questions and they have different
answers.

---

## The Kalshi pricing wedge — result

`pm/` — replication and honest-cost audit of Yang (2026), *Pricing Prediction Markets:
Incomplete Markets, Selection Rules, and Risk Premia*. Full write-up:
[`docs/KALSHI_WEDGE_RESULT.md`](docs/KALSHI_WEDGE_RESULT.md).

The paper fits a Wang transform to 291,309 resolved prediction-market contracts,
`p_mkt = Φ(Φ⁻¹(p*) + λ)`, and finds λ ≈ 0.178 on Kalshi — prices sitting systematically above
true probabilities, with the wedge larger where volume is lower and duration longer.

It estimates λ on hourly **mid** prices. Kalshi's candlestick endpoint also returns `yes_bid`
and `yes_ask`, so I re-estimated on the price a taker could actually hit. On 17,671 settled
2026 contracts:

| Estimator | λ | t |
| --- | --- | --- |
| Complement-invariant, at the mid | **+0.036** | +3.45 |
| Complement-invariant, **at the executable bid** | **−0.441** | −39.3 |

The spread cut says why:

| Spread | λ at mid | λ at executable |
| --- | --- | --- |
| tight ≤2c | −0.060 | −0.081 |
| 2–10c | −0.031 | −0.113 |
| wide >10c | **+0.114** | **−1.007** |

Where the book is tight there is no positive wedge at all. The entire effect lives in books
wider than 10 cents and inverts when priced at the bid. Selling the longshot at the executable
price loses 6–17 cents per contract before fees, at every price level.

**The volume cross-section does replicate** and is not a spread artifact — terciles run
+0.181 / +0.038 / −0.094 across nearly identical median spreads (8c / 8c / 7c). **The duration
effect does not**: its terciles run 4c → 6c → 18c in spread, so duration and spread are the
same fact wearing two hats.

Survives an event-clustered bootstrap (t = 3.30), leave-largest-series-out, and a sports /
non-sports split. I could **not** reproduce the paper's level — 0.025–0.048 against its 0.172
for the same year, across every variant of filter, price field and specification I tried. One
candidate explanation (that its Kalshi sample keeps the crypto randomness shards its Polymarket
sample excludes) was tested directly and rejected: those contracts give +0.041, indistinguishable
from the main sample. The discrepancy is documented rather than resolved, and it does not touch
the audit's conclusion, since the mid and executable estimates are computed on the same contracts.

**Conclusion: the wedge is the spread.** It is a risk premium paid to makers for bearing
inventory and adverse-selection risk in thin markets, not an edge available to a taker. "Avoid
the markets the quant shops make" correctly describes where λ lives and is useless as a trading
instruction, because the reason it lives there is that nobody wants to quote those books.

## Layout

```
toolkit/       harness.py (the falsification engine), tests.py (the 5 self-tests)
scripts/       individual studies — each one produced a row in the graveyard
docs/          LEAK_CHECKLIST.md, and per-study write-ups
pm/            prediction-market work: Kalshi collector + wedge estimation
```

`data/` is not in this repo — it is ~1.1 GB of futures bars and option chains, and most of it
is not mine to redistribute.

## Running it

```bash
pip3 install pandas numpy scipy
python3 toolkit/tests.py      # 5 self-tests, ~25s, all must pass
```

If the self-tests do not all pass, the harness is untrustworthy and so is every number it
ever produced. That check comes first.
