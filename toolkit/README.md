# toolkit/harness.py — the leak-proof backtest harness

Every backtest goes through this. No PF reaches the screen unless it came out of `audit()`.

## Usage

```python
from harness import load_bars, audit

bars = load_bars("../data/pkl/nq_5m_all.pkl")
v = audit(my_signal, bars, stop=0.0015, target=0.004)
v.report()          # honest number only, with every check shown
```

That's the whole workflow. Write a `signal()`, run `audit()`, read the verdict. If it doesn't say
PASS with a clean report, it doesn't go on the screen as an edge.

## Writing a signal

```python
def my_signal(day, g):
    """day = 'YYYY-MM-DD', g = that day's bars (columns m,o,h,l,c), indexed 0..n-1."""
    out = []
    for i in range(1, len(g)):
        if <some condition using ONLY bars 0..i>:
            out.append((i, -1))          # (bar index, +1 long / -1 short)
            # or (i, -1, level) if you want audit to measure the lookahead gap
    return out
```

The harness fills at bar `i+1`'s **open**. There is no "fill at the level."

## Run the self-tests

```
python3 toolkit/tests.py
```

Five tests, all must pass (~25s). Four prove it says NO to different fakes — the real 2026-07-20
band fade, a signal that peeks at future bars, pure coin flips, and a cherry-picked parameter — and
the fifth proves it still says YES to a synthetic edge that is genuinely real. A harness that only
ever says NO is a wall, not a filter; **T4 is what makes the other four mean anything.**

## Costs: this is prop-firm research, so the headline is gross

`cost=0.0` and `slippage_ticks=0` by default. Two things worth knowing anyway:

- Prop firms **do** charge commissions (~$3–4 round-turn on NQ at Apex/Topstep), and stop orders
  slip regardless of who pays. The report's **1-tick stress line is a thinness gauge, not a cost
  model** — it tells you how much edge survives contact with reality. It is reported, not gated.
- Stripping costs makes the naive `PF > 1.05` gate much easier to clear. That is exactly why T5
  exists: the cherry-picked band fade prints 1.06 gross and is still worthless.

**No drawdown or ruin gate**, by Igor's call. Account survival is a position-sizing question, not an edge
question — gating on it fails a strategy for being sized wrong, which is a different bug than not having an
edge. It's a game of convexity and speed; size it after you believe it.

## The checks in `audit()`

A verdict passes only if **all** of these hold:

| check | why |
|---|---|
| honest PF > 1.05 | the only number that counts |
| ≥100 trades | a PF on 40 trades is an anecdote |
| beats p75 of random entries | otherwise your *exits* are the artifact, not your signal |
| beats p75 of shuffled levels | otherwise the level carries no information |
| bootstrap 5th pct PF > 1.0 | an error bar: can you tell it apart from noise? |
| PF > 1 in ≥60% of years | a plateau in time, not one lucky year |
| out-of-sample (last 30%) PF > 1.0 | you chose your thresholds looking at this data |
| survives dropping the top 1% of trades | not three monster days carrying a thousand |
| parameter plateau, not a spike | median of the grid must clear 1.05, not just the best cell |
| honest edge isn't just the lookahead gap | the 2026-07-20 bug, encoded as a rule |

Reported but **not** gated: low-vol vs high-vol PF, long vs short PF, 1-tick stress. Real edges are
often one-sided or regime-dependent — you should just know which one you have before sizing it.

The shuffle check only runs if you pass `level_shuffler=f(rng) -> signal`. The plateau check only
runs if you pass `signal_factory=` and `grid=`.

## The overfit scan

```python
factory = lambda band: my_signal(band=band)
v = audit(factory(0.0027), bars,
          signal_factory=factory,
          grid={"band": [0.002, 0.0025, 0.0027, 0.003, 0.0035]})
```

It runs the honest backtest over the whole cartesian product and judges the **median** cell, not
the best one. If your rule is real it should still work when you nudge the knobs; an edge that
lives at 0.0027 and dies at 0.0025 is a fit to noise.

Reporting the best cell of an N-cell scan as "the" result is how PFs get manufactured — the more
combinations you try, the higher the best one goes on pure chance. T5 demonstrates this end to end.

## Inspecting individual trades

`backtest()` returns a list of `Trade` namedtuples — `day, year, i, direction, entry, exit, ret,
bars_held`. A leak-free backtest of the *wrong strategy* is still worthless, so read some:

```python
for t in v.honest_trades[:10]:
    print(t.day, t.direction, round(t.entry, 2), round(t.exit, 2),
          f"{t.ret:+.4f}", f"{t.bars_held} bars")
```

If `bars_held` is 0 constantly, or every entry is at a suspiciously round price, that tells you
something no aggregate statistic will.

## Deviation from BUILD_HARNESS_FIRST.md — read this once

The spec predicted the honest band-fade PF would be **~1.02**. This harness reports **0.94** with
the spec's cost assumption, and **1.03** gross (the current default). Neither is a bug. The main
difference is one line: which bar the exit scan starts on.

- `honest_backtest.py` (the older seed) enters at bar `i+1`'s open but starts checking stop/target at
  bar **`i+2`** — the bar you entered on can never stop you out. That gives ~1.02.
- `harness.py` scans from bar **`i+1`** — the entry bar *can* stop you out, which is what happens in
  real life.

The harness uses the conservative one, by Igor's decision. Both agree the band fade is dead; the
1.74 → ~1.0 collapse is identical either way.

## Note on the ⚠ banner appearing on a PASS

T4's real edge still prints `⚠ LOOKAHEAD DETECTED` (level-fill 8.51 vs honest 1.57). That is
correct and intended. It says "the level-fill number is a lie" — which it is — while the honest
number stands on its own merit. The banner flags the *gap*, not the verdict. The lookahead number
is never printed without it.
