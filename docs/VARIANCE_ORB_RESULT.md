# RESULT — HarvestPremia variance framework, Template 1 (ORB). Dead on NQ.

*Measured 2026-08-20. Papers: `docs/reference/variance_regimes_paper1.pdf` (regimes),
`variance_models_paper2.pdf` (the models), `quant_methods_hp.pdf` (methodology).
Code: `scripts/orb_harvestpremia.py`, `orb_filters.py`, `orb_longonly_beta.py`.*

---

## What the papers actually claim

**Paper 1 ("Identifying Tradeable Variance Regimes")** contains **no entry rule at all.** It is four
screens — GARCH percentile, VIX 13–35 + term structure, event-calendar tier, Hurst 60–90d — plus a
discretionary tape layer. It gates trading; it never says what to trade. The handoff assumed this was
the testable paper. It isn't.

**Paper 2 ("Variance Models for Prop Firm Trading")** holds the mechanical claims: four templates with
ATR-anchored exits. **Template 1 (ORB) is the most concrete thing in the entire framework.**

**Paper 3 (quant methods)** is generic methodology (IC/ICIR, Deflated Sharpe, PBO, purged k-fold).

**No performance number appears anywhere in the three papers** — no PF, no win rate, no pass rate.
Paper 2 Table 5 states all metrics are computed "on live account data, not backtests." There was no
claimed magnitude to falsify; the test was whether the mechanism exists at all.

## The rule tested (Paper 2, Table 1) — zero free parameters

> High/low of 09:30–09:45 ET. First 5-min bar **closing** outside it is the trade (long above / short
> below). TP 1.5×ATR(5), SL 0.5×ATR(5), flat at 10:30 ET regardless. Filters: ATR(20) > its 50th pct
> over 20 sessions, Hurst > 0.50.

Mechanism claimed: overnight information reprices at the open, the first 15 min bound that repricing,
a break means repricing is **incomplete and continues**. 3:1 RR → breakeven win rate 25%.

Nothing here was tuned. Every number is the paper's. That is the one genuinely strong property of this
test — the usual overfitting critique does not apply.

## Result: DEAD. NQ 5m, 2015-01-02 → 2026-01-30, 2857 sessions.

Each variant is judged against its **own matched direction-flip null**: same day, same entry bar, same
ATR exits — only the side is randomized, 200 seeds. n matches exactly.

| variant | n | PF | WR | null median | p |
|---|---|---|---|---|---|
| A naked ORB | 2495 | 1.017 | 0.341 | 1.013 | **0.460** |
| B + ATR20 > 20-sess median | 1202 | 1.005 | 0.337 | 1.034 | 0.700 |
| C + Hurst > 0.50 (paper) | 2096 | 1.037 | 0.344 | 1.016 | 0.360 |
| D full Table 1 (ATR + H>0.50) | 991 | 1.022 | 0.338 | 1.054 | 0.655 |
| E D + VIX 18–35 | 271 | 1.161 | 0.373 | 1.133 | 0.405 |
| F ATR + H>0.69 (top quartile) | 275 | 1.046 | 0.338 | 1.074 | 0.595 |

Best p over six variants is 0.36. Nothing survives.

**The trap variant E would have set.** PF 1.161 with the "best regime" VIX filter looks like the regime
story working. Its own null is 1.133. The filters raise the real PF *and the null PF together* — they
select higher-volatility sessions where the ATR-barrier machinery does better on its own. Without the
matched null, E is a publishable-looking result. It is noise on n=271.

### The level-fill lie, reproduced inside the mentor's framework
Paper 2 Table 1 says "entry at 09:45 break" **and** "on close of bar" — two different trades. Filling at
the range edge (a resting stop order) prints **PF 2.35**. Honest next-open fill: **1.02**. A 1.33 PF gap.
This is the same failure as the 2026-07-20 fake 1.74, arriving from a new direction.

### Confirmation with the exit engine removed
Forward return from the next open, no stops or targets, breakout bars vs all bars in the same window:

| horizon | breakout | unconditional | diff | t |
|---|---|---|---|---|
| 6 bars | 0.63 bps | 0.20 bps | +0.43 | 0.59 |
| 12 bars | 0.94 bps | 0.41 bps | +0.53 | 0.53 |
| 24 bars | 0.45 bps | 0.75 bps | −0.30 | −0.23 |

The breakout carries no forward-return information at any horizon. This is assumption-free — no barriers,
no exit logic — and it agrees with the matched nulls.

## Two independent findings about the framework's own filters

**1. The Hurst filter is miscalibrated and is close to a no-op.** The R/S estimator has a known
small-sample upward bias: on a *synthetic iid random walk* at a 90-day window it returns **H = 0.628
(sd 0.111)**, not 0.50. Real NQ trailing-90d Hurst is **mean 0.620, sd 0.105** — statistically
indistinguishable from that random-walk null. Consequences:

- "H > 0.50 = trending" passes **86.6%** of NQ sessions. "H > 0.55" passes 74.8%.
- "Stand down if H < 0.45" fires on 5.8% of sessions.
- NQ daily returns show no persistence this estimator can detect.

Any strategy gated on `H > 0.50` at a 90-day window is essentially ungated, and the regime label it
assigns is not measuring persistence. **Before using a Hurst threshold, calibrate the estimator against
a random-walk null at your actual window length.** The paper's thresholds appear to assume the textbook
H=0.5 null, which does not hold at n=90.

**2. The variance filters select vol, not direction.** Every filter raised the null PF as much as the
real PF (table above). They identify sessions where price moves more — which is exactly what Paper 1
claims they do — but movement magnitude does not convert into a directional edge through this entry.
Paper 0's convexity thesis is not the thing failing here; the *entry* is.

## Igor's long-only variant — it's beta, not edge

Long-only NQ, 09:30–10:00 range, 1:2 RR (SL 1.0×ATR(5) / TP 2.0×ATR(5)), `scripts/orb_longonly_beta.py`:

| | n | PF | WR (breakeven 0.333) |
|---|---|---|---|
| long ORB breakout | 1888 | 1.068 | 0.379 |
| **always-long at 10:00, no condition** | 2853 | **1.060** | 0.350 |

RTH open→close buy-and-hold is **+2.49 bps/day** over 2857 sessions. NQ ran ~4,000 → ~22,000 across the
sample, so PF > 1 is the default for anything long-only, not evidence. The breakout condition moves PF
from 1.060 to 1.068 — it adds essentially nothing over simply being long. "Smart beta" is the accurate
name; there is no alpha in the breakout half.

*Caveat recorded honestly:* a long-only **random**-entry null printed 1.40, far above the real 1.068,
and that gap is **not** explained by forward returns (which are flat, table above). It is a
barrier-placement effect — a stop 1 ATR below a breakout extreme sits inside recent chop, while the
same barrier around a typical intraday price does not. I do not fully account for its size, so the
conclusion above rests on the always-long benchmark and the forward-return test, **not** on that null.
Long-only random-entry nulls are unreliable in a drifting market; don't reuse that comparison.

## Not tested, and why

Templates 2 (Event Continuation) and 3 (Event Fade) are gated on Tier 1 macro releases (FOMC/NFP/CPI).
There is no economic calendar in `data/`. They remain **untested**, not disproven. Template 4 (Negative
RR Scalp, needs >75% win rate) is testable on existing data but has a VWAP-definition ambiguity.

## Harness change made for this

`backtest()` gained `exit_by=` — an **absolute** bar-index cutoff, distinct from `max_hold` (which counts
from the trigger). Needed because Table 1 says "close at 10:30 ET regardless", a wall-clock time, not a
holding period. All 5 self-tests re-run and pass.

New data: `data/pkl/vix_daily.pkl` (VIX 5-min → daily OHLC, 1456 sessions 2020-01-02 → 2025-10-16) and
`data/pkl/orb_regime.pkl` (per-session ATR20/Hurst/VIX, every column shifted to prior sessions only).

---

# UPDATE 2026-08-20 (same day) — Templates 2 and 3 tested on FOMC. Also dead.

## The calendar

FOMC statement dates 2015–2026 sourced from federalreserve.gov (`fomccalendars.htm` +
`fomchistorical<YYYY>.htm`), built by `scripts/build_fomc_calendar.py` → `data/pkl/fomc_calendar.pkl`.
95 scheduled meetings, 88 falling inside the NQ sample. The two 2020 emergency actions (Mar 3, Mar 15)
are recorded but flagged **unscheduled** and excluded: nobody could position for them ex-ante, and
Template 2 is explicitly a scheduled-release model.

**Validated before use** — NQ 5-min |return| by minute, FOMC vs all other sessions:

| ET | FOMC | other | ratio |
|---|---|---|---|
| 12:30 | 4.43 bps | 6.37 | **0.70×** |
| 13:30 | 5.13 | 6.41 | 0.80× |
| **14:00** | **30.81** | 7.09 | **4.34×** |
| 14:30 (presser) | 17.40 | 6.33 | 2.75× |

Dates and the ET→CT conversion are both correct. **This also confirms a Paper 1 claim**: "FOMC morning
sessions are typically low variance before the 14:00 decision... reserve capital for the 13:45–14:05
window" is empirically true — pre-event variance is 0.70× normal, the release is 4.34×. Paper 1's
*variance* description of FOMC is accurate. What fails is converting it into directional edge.

NFP and CPI remain unsourced: bls.gov and alfred.stlouisfed.org both refuse automated fetches (403),
and Bash has no network to those hosts. They print at **08:30 ET — before the RTH open** — so they also
need a full-session NQ rebuild from the 1-min raw (which does cover all 24h, verified).

## Results — 88 FOMC sessions, honest next-open fills, `strict=True`

**Template 2 — Event Continuation**, at the paper's own parameters (SL 0.5 / TP 1.0 × ATR(5), 20 min):

    n=65   PF=1.102   WR=0.323 (breakeven 0.333)   direction-flip null median 0.679, p=0.018

p=0.018 looks like a hit. It is not. The full battery:

| check | value |
|---|---|
| **PF without the single best trade** | **0.986** |
| bootstrap 90% CI | [0.66, 1.74] |
| in-sample / out-of-sample | 1.26 / 0.81 |
| years with PF > 1 | 42% |
| PF dropping top 1% | 0.68 |

One trade (2018-12-19, +23.7 bps) is the entire edge. `strict=True` passed, so this was not a leak —
it was noise plus concentration. Per-year is wild: 0.24, 0.66, 0.71, 0.67 in four years against 4.93
in 2020 and 3.54 in 2019.

**Template 3 — Event Fade**: n=27, PF=0.495, WR 0.556 vs breakeven 0.667, p=0.200. Dead.

## The structural finding: Paper 2's ATR calibration is wrong-scaled for event models

62 of 65 Template 2 trades exited on the **first bar after entry**. Cause — post-release 5-min bar range,
in units of the pre-event ATR(5) the paper sizes stops with:

| bar | median range | % exceeding 1.5 ATR |
|---|---|---|
| 14:00–14:05 | **5.27 ATR** | **99%** |
| 14:05–14:10 | 3.14 | 88% |
| 14:10–14:15 | 2.38 | 83% |
| 14:15–14:20 | 2.23 | 80% |

Template 2's entire barrier width is SL 0.5 + TP 1.0 = **1.5 ATR**, which a single post-event bar
swallows 99% of the time. **The model described in Table 2 — 2:1 RR, 20-minute hold, 33% win rate —
does not exist at those parameters.** It is a coinflip on intrabar path, unresolvable from 5-min OHLC.
Paper 2 Part II argues ATR "scales automatically" across regimes; it does not scale across the
pre-event → post-event discontinuity, which is a 4–5× jump inside one bar. Any event model calibrated
on pre-event ATR has barriers narrower than the noise it is deployed into.

## Re-sized barriers: the mechanism is dead independently of the sizing bug

Labelled deviation — barriers set on the **release bar's own range** (known at its close, strictly before
entry), which is the correctly-scaled version of the paper's idea:

| model | n | PF | WR | exit-bar distribution | null median | p | PF w/o best |
|---|---|---|---|---|---|---|---|
| T2 continuation | 65 | 1.016 | 0.492 | 50 of 65 run full window | 0.874 | **0.290** | 0.908 |
| T3 fade | 27 | 0.519 | 0.296 | 24 of 27 run full window | 1.055 | **0.892** | 0.378 |

Exits now behave as designed, and the edge is gone. The p=0.018 at the paper's parameters was the
mis-scaled barriers plus one trade, not a signal.

## Framework scorecard

| claim | status |
|---|---|
| Paper 0 — convexity/variance thesis | confirmed earlier (`docs/PROPFIRM_COINFLIP_EV.md`) |
| Paper 1 — FOMC pre-event compression, release spike | **CONFIRMED** (0.70× / 4.34×) |
| Paper 1 — Hurst regime filter | **miscalibrated**; ~no-op at H>0.50, n=90 |
| Paper 2 — T1 ORB | **DEAD**, 6 variants, best p=0.36 |
| Paper 2 — T2 Event Continuation | **DEAD**, p=0.29 correctly sized; one trade at paper params |
| Paper 2 — T3 Event Fade | **DEAD**, PF ~0.5, p=0.89 |
| Paper 2 — ATR(5) calibration for events | **structurally wrong-scaled** (5.27×) |
| Paper 2 — T4 Negative RR Scalp | untested (VWAP ambiguity) |
| T2/T3 on NFP and CPI | untested (calendar unsourced + needs full-session rebuild) |

The framework's *descriptive* claims about variance hold up. Every *directional* claim tested so far
does not. That is the same pattern as the options thread: the phenomenon is real, the edge is not.
