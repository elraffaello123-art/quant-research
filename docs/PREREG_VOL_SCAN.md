# Pre-registration — volatility-structure scan on GC / SI / CL

**Frozen 2026-07-21, BEFORE any backtest in this study was run.**

The point of a pre-registration is that the search space is fixed in advance. A scan is only
more honest than one-idea-at-a-time if the correction is computed over the *declared* set. If
cells get added after seeing results, this is worse than testing a single hypothesis, not better.

**Nothing below may be edited once the first `audit()` in this study runs.** If a genuinely new
idea appears mid-scan it goes in `PREREG_VOL_SCAN_R2.md` as a separate, separately-corrected
study. Changing this file after the fact invalidates every number that comes out of it.

---

## 1. Why this study

Every previous thread died the same way: the signal was real as a *description* but not as a
*forecast at next-bar-open*. Options aggregates were price in a costume (`net_gex` R²=0.73 on
spot); `skew` was independent but not predictive (whole effect = one NQ tick); L2 imbalance
decayed sub-second; ORB metalabeling sat inside its shuffled-label null (p=0.155).

This study changes the *source of structure*, not the method. GC/SI/CL have calendar and session
structure that index futures lack: scheduled catalysts at fixed clock times, three trading
sessions with real handoffs, physical delivery and inventory cycles. That is a recurring,
**timeable** source of volatility, and it has not been tested here.

Igor's prior — that metals/oil are "less liquid so edge is more frequent" — is not the
justification. Liquidity is not what kills an edge. The justification is calendar structure.

## 2. Data (built by `scripts/build_futures_5m.py`, Phase 0, complete)

| file | span | bars/day |
|---|---|---|
| `data/pkl/{gc,si}_5m.pkl` | 2020-01-02 → 2026-02-17 | 78 (RTH 09:30–15:55 ET) |
| `data/pkl/cl_5m.pkl` | 2021-01-04 → 2024-12-31 | 78 (RTH) |
| `data/pkl/{gc,si,cl}_5m_full.pkl` | same spans | 276 (24h session) |

Columns `d,m,o,h,l,c,v`; the 24h files add `et`.

- **`m` in the 24h files is minutes since 18:00 ET**, not since midnight, so it sorts
  chronologically within a session. `et` preserves the wall clock for time-of-day rules.
- **Session date ≠ calendar date.** Bars from 18:00 ET on are rolled to the next day, so the
  overnight *preceding* a session groups with it. Verified on GC 2024-03-14.
- **CL starts 2021-01-04**: excludes the April-2020 negative-price break, and coincides exactly
  with the options-data start, so Phase 3's sample would need no additional choice.
- CL bad-tick threshold is 10%, not 2%. At 2% the filter silently deleted the 2020-04-21
  collapse — the largest real vol event in oil's history — from a volatility study.

**Coverage is unequal.** All cross-instrument comparisons are run on the common window
2021-01-04 → 2024-12-31, never on each instrument's full span.

## 3. Final holdout — untouched until the scan is over

| | scan window | FINAL HOLDOUT |
|---|---|---|
| GC, SI | 2020-01-02 → 2024-12-31 | **2025-01-01 → 2026-02-17** |
| CL | 2021-01-04 → 2024-06-30 | **2024-07-01 → 2024-12-31** |

The holdout is not loaded during the scan. `audit()`'s own last-30% OOS check operates *within*
the scan window; the holdout is a second, stricter block that no parameter has ever seen. Only
cells that survive Section 6 are run on it, once. If a survivor dies on the holdout, it is dead —
no re-fitting, no "the regime changed."

When Igor sources CL data past 2024-12, it becomes additional untouched holdout. It is worth
more after the parameters are frozen, so it should not be fetched before then.

## 4. Exit convention — ATR units, not fixed percentages

Median 5-min vol is GC 0.059%, SI 0.117%, CL 0.152%. A fixed 0.15% stop is a normal-sized stop
on gold and *inside a single average bar* on oil. Fixed-percentage exits would mean the three
instruments are running three different strategies, and the cross-instrument check — the primary
filter in Section 6 — would be meaningless.

`ATR` := mean of `(session high − session low) / session close` over the **14 sessions strictly
before** the current one. Computed at load time, never from the current session.

- `stop   = ks × ATR`, `ks ∈ {0.5, 1.0}`
- `target = kt × ATR`, `kt ∈ {1.0, 2.0}`
- max hold: **36 bars fixed** (3h RTH). Not a scanned parameter.

→ **4 exit combinations**, applied identically to every cell below.

## 5. The three families — the complete declared search

Direction is stated per rule; no cell is free to pick its sign after the fact.

### Family A — scheduled catalyst (32 cells/instrument)
Catalyst time `T`: **CL** = Wed 10:30 ET (EIA, `et=630`); **GC/SI** = 08:30 ET daily
(`et=510`, US macro releases).
- pre-event range window: `{6, 12}` bars ending at `T`
- entry rule: `{breakout of pre-event range, fade of first post-event bar extreme}`
- delay after `T`: `{1, 3}` bars
- → 2 × 2 × 2 = 8 × 4 exits = **32**

### Family B — compression → expansion (24 cells/instrument)
- lookback `L`: `{12, 24, 48}` bars
- compression trigger: `L`-bar range in the bottom `{20th, 35th}` pct of the trailing 60
  sessions **at the same time of day** (a 12-bar range at 09:35 is not comparable to 14:00)
- entry: break of the `L`-bar high (long) / low (short)
- RTH only, fixed
- → 3 × 2 = 6 × 4 exits = **24**

### Family C — session handoff (48 cells/instrument)
- prior window: `{overnight (m 0–930), London (m 540–930)}`
- signal: `{continuation of that window's direction, fade of its extreme}`
- condition on that window's range tercile (vs trailing 60 sessions): `{low, high, none}`
- entry only after RTH open (`m ≥ 930`)
- → 2 × 2 × 3 = 12 × 4 exits = **48**

**Total: 104 cells × 3 instruments = 312 backtests.** This number is fixed and is the
denominator for Section 6.

## 6. Decision rules — declared in advance

With 312 tests, ~15 will clear p<0.05 by chance alone. A bare PF means nothing here.

1. **Every cell goes through `audit()`.** No hand-rolled loops, next-open fills, `strict=True`.
2. **Cross-instrument agreement (primary filter).** A cell must pass in **≥2 of 3 instruments
   with the same sign**. Three different markets with different participants sharing a
   microstructural mechanism is a far harder filter than any single-instrument statistic, and
   it is free. This is the main defense against the failure mode that has burned this project.
3. **Search-corrected null (mandatory).** Re-run the **entire 312-cell scan** on day-shuffled
   labels, ≥200 repetitions, and record the *maximum* PF each repetition. The real best cell
   must exceed the **p95 of that max-PF null**.
   This is the specific lesson from the ORB metalabel failure: the null must be "the maximum
   over a 312-cell search," not "one test." A selected-PF of 1.274 looked great until the null's
   p90 turned out to be 1.306.
4. **Holdout (Section 3), run once**, only on cells passing 1–3.
5. **1-minute robustness.** Any survivor is re-run on the 1-min data. 5-min bars are a
   *convention* inherited from the harness, not a finding. If a result depends on where the
   5-min grid happens to fall, it is a sampling artifact.

## 7. What is NOT in this study

- **Options.** Off the critical path by Igor's call (2026-07-21). GLD/SLV/USO daily snapshots
  end 2024-03; closing the gap to 2026 means crawling ~450 daily zips off IPFS. Deferred to
  Phase 3, and only if Phase 2 yields a survivor worth conditioning — at which point we will
  know exactly which tickers and dates to pull. If it runs, IV gets the `net_gex` guard test
  first: does it add anything over an EWMA-of-realized-vol baseline, or is it realized vol in
  an options costume?
- **NQ / ES.** Excluded by Igor's call.
- **L2.** Dead by prior measurement; not revisited here.

## 8. Expected outcome

Most likely: nothing survives Section 6. That is the base rate, and this document exists so
that a negative result is *informative* rather than an invitation to keep searching until
something turns up. If all 312 cells die against a properly search-corrected null, the honest
conclusion is that intraday volatility structure in these three commodities does not carry a
directional edge at 5-minute resolution — which closes a large branch cleanly.
