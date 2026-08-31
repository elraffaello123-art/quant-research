# Backtest audit checklist — how to catch a fake edge

*Run these against every backtest before believing any number.*
*Ordered by how often they're the culprit. #1 catches the most.*

---

## 1. Honest fills — the next-open diff  ⟵ START HERE, catches the most
**The test:** re-run the strategy filling entries at the **next bar's open** instead of "at the level."
If the PF changes, the original was **lookahead**. Report only the honest number.

**Why it happens:** a strategy enters at a price level (wall, band, breakout, pin). The code fills *at the level*
on the trigger bar, but also uses that bar's **close** to decide whether to keep the trade (e.g. "only if it
closed back inside"). That silently discards the fills that became losers — you're picking winners with hindsight.
In reality a resting order fills on every touch; you can't drop the losers after the fact.

**Real example (2026-07-20):** NQ band-fade showed PF 1.74. Fill at next-open → **1.02**. The whole "edge" was
this one line. `toolkit/honest_backtest.py` has `run_fade(entry='atlevel' | 'nextopen')` — flip it and diff.

**Demands this check:** PF > 1.5 on a mechanical rule · "positive every single year" · win-rate far above the
reward:risk breakeven (breakeven WR ≈ 1/(1+RR)) · any entry that fills exactly at a level.

## 2. Random-entry placebo — is it the exit machinery?
Enter at **random times and random sides**, run through the **same exit logic**. If random also prints a high PF,
your *exits* are the artifact (stops filled at exact price, target-checked-before-stop, EOD exits uncapped), not
your signal. A real signal beats random entry clearly.

## 3. Shuffle placebo — does the "level" actually matter?
Shuffle the special levels to random-but-realistic prices (e.g. shuffle option open-interest across strikes, or
jitter the pin ±1%). Re-run. If the real levels don't clearly beat the shuffle, the level carries **no
information** — the P&L is generic structure, not the edge. (This is how we proved gamma walls ≈ random strikes.)

## 4. Per-year / per-regime breakdown
One blended PF hides everything. Split by year. A real edge is a **plateau** across years; a fake one is carried
by one or two lucky years. Also check trending vs chop, high vs low vol.

## 5. Stop fill-fiction
Stops filled at the *exact* stop price are optimistic. Model a **gap-fill** (fill at the bar's open when it opens
beyond the stop) plus 1–2 ticks slippage. If PF craters, the edge was fill fiction. (Wins via limit target are
fine to fill at the target — gapping through a limit favors you.)

## 6. Feature lookahead
Every input to a decision must be knowable **before** the decision bar.
- Open interest is reported T+1 → prior-day OI is safe, same-day is a leak.
- "Prior-day" filters that secretly use same-day data (e.g. today's realized vol as a "filter").
- Dominant-contract-per-day chosen with **full-day** volume (uses the future) — usually harmless for level
  selection, but know you're doing it.
- Contract-roll gaps polluting overnight levels.
Check the timestamp of every column you feed the rule.

## 7. Replication check — did the code match the idea?  (separate from leaks)
A leak-free backtest of the *wrong strategy* is still worthless. Restate the strategy in plain English, then trace
each line to a word:
- Right **direction** (fade vs momentum, long vs short)?
- Right **session/time** filter, right timezone (NQ bars here are CENTRAL time)?
- **One trade per day** or many? First-touch or every-touch?
- **Costs** realistic (NQ round-trip ≈ 0.5–1 bp)?
- Target/stop on the **correct side** of entry? (A flipped stop sign once gave a fake 100% win-rate here.)
Make the AI show you the entry/exit block and read it against your words. If you can't map every line, don't trust it.

---

### The one-liner to remember
**Make the AI fill at the next bar's open. If the number moves, it was a lie.** Everything else is refinement.
