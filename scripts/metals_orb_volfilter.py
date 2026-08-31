"""
metals_orb_volfilter.py — the one thing that replicated, tested as a rule.

WHAT SURVIVED TODAY. The raw ORB failed (PF 1.13 on MGC but 1.08 on independently-sourced GC,
bootstrap 5th pct < 1.0 — a sample-window artifact). ML meta-labeling failed (AUC ~0.50,
permutation p=0.155-0.375). What replicated across three series and two markets is the
volatility split:

    low-vol / high-vol PF     MGC 0.39/1.94    GC 0.38/1.84    SI 0.46/1.95

Breakouts need something to break out into. This tests that as a mechanical rule.

*** THE HONESTY PROBLEM WITH THIS TEST, STATED UP FRONT ***
I have already SEEN that split. Conditioning on it is data-snooped by construction — that is
unavoidable now and must not be hidden. Three things keep it as honest as it can be:

  1. The threshold is EX ANTE and not tuned: "prior-day ATR20 above its own trailing median."
     No search over percentiles picking the best one. One obvious rule, taken as-is.
  2. It is STRICTLY CAUSAL: ATR20 uses prior days only (shift(1)); the median it is compared
     against is a TRAILING 250-day median, not the full-sample median. Using the full-sample
     median would leak the future into the regime label — the classic version of this mistake.
  3. It must hold on ALL THREE series. Passing on one instrument means nothing; that is exactly
     how the raw ORB fooled us this morning.

If it passes here it is still not deployable — it is a candidate that has earned a walk-forward
re-test on data none of today's decisions touched.

Run: python3 scripts/metals_orb_volfilter.py
"""
import sys

import pandas as pd

sys.path.insert(0, "toolkit")
sys.path.insert(0, "scripts")
from gold_orb_audit import orb_signal          # noqa: E402
from harness import audit, load_bars           # noqa: E402

N_BARS = 6
STOP, TARGET = 0.003, 0.006
MED_WINDOW = 250          # trailing window for the regime threshold


def vol_regime(bars):
    """{day: True if prior-day ATR20 is above its own TRAILING median}.

    Every term is shifted so the label for day D uses only data through D-1.
    A full-sample median here would be lookahead: it would let 2021 know how volatile
    2025 turned out to be.
    """
    d = pd.DataFrame(
        {day: {"h": g["h"].max(), "l": g["l"].min(), "c": g["c"].iloc[-1]}
         for day, g in bars.items()}
    ).T.sort_index()
    tr = (d["h"] - d["l"]) / d["c"]
    atr20 = tr.rolling(20).mean().shift(1)                       # prior days only
    med = atr20.rolling(MED_WINDOW, min_periods=60).median()     # trailing, no future
    return (atr20 > med).to_dict()


def filtered_signal(regime, n_bars=N_BARS, want_high=True):
    """The ORB, but only on days whose regime flag matches."""
    base = orb_signal(n_bars=n_bars, fade=False)

    def signal(day, g):
        flag = regime.get(day)
        if flag is None or bool(flag) != want_high:
            return []
        return base(day, g)
    return signal


def run(name, tick):
    bars = load_bars(f"data/pkl/{name}_5m.pkl", min_bars=60)
    regime = vol_regime(bars)
    hi = sum(1 for v in regime.values() if v is True)
    print("\n" + "#" * 72)
    print(f"#  {name.upper()}  —  {len(bars)} days, {hi} in high-vol regime")
    print("#" * 72)

    factory = lambda n_bars: filtered_signal(regime, n_bars=n_bars, want_high=True)
    v = audit(factory(N_BARS), bars,
              stop=STOP, target=TARGET, one_per_day=True, tick=tick,
              signal_factory=factory, grid={"n_bars": [3, 6, 9, 12, 18]})
    v.report()

    # the mirror: low-vol days should be BAD. If they're also fine, the filter isn't
    # separating anything and the split we saw was noise.
    print(f"\n  -- control: same rule on LOW-vol days only --")
    lo = audit(filtered_signal(regime, want_high=False), bars,
               stop=STOP, target=TARGET, one_per_day=True, tick=tick)
    print(f"     low-vol honest PF: {lo.honest_pf:.3f}  (n={len(lo.honest_trades)})")
    return v


if __name__ == "__main__":
    for name, tick in [("gc", 0.10), ("si", 0.005), ("mgc", 0.10)]:
        run(name, tick)
