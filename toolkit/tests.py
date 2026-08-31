"""
tests.py — the harness's own self-test. Run it any time:

    python3 toolkit/tests.py

Five tests. The harness is only trustworthy if ALL FIVE pass, because together
they prove it can say NO to four different kinds of fake and still say YES to
something real:

    T1  the actual 2026-07-20 bug (NQ band fade)   -> must FAIL
    T2  a signal that openly reads the future      -> must FAIL, flagged as lookahead
    T3  pure coin-flip entries                     -> must FAIL, PF about 1.0
    T5  the best cell of a 9-parameter scan        -> must FAIL
    T4  a synthetic, genuinely real edge           -> must PASS

A harness that only ever says NO is not a filter, it is a wall. T4 is what makes
the other four mean something.
"""

import os
import sys
import traceback

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (  # noqa: E402
    PF, audit, backtest, band_fade_signal, load_bars, overfit_scan,
    planted_lookahead_signal, synthetic_bars,
)

NQ = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                  "..", "data", "pkl", "nq_5m_all.pkl")
N_PLACEBO = 10


def banner(title):
    print("\n" + "#" * 68)
    print(f"#  {title}")
    print("#" * 68)


def random_signal(seed=0, fire_prob=1.0 / 78):
    """
    Coin-flip entries: walk the bars and fire with a small probability each bar,
    then pick a random side.

    Note this is written CAUSALLY on purpose. The obvious version — "pick one
    uniform random bar out of today's n bars" — needs to know n, the day's total
    length, which you don't know at bar 7. strict=True correctly rejects it.
    Drawing per bar in order needs no such knowledge, and re-running on truncated
    data reproduces the identical draws. The rng is seeded from the date so the
    signal is a deterministic function of what it is shown.
    """
    def signal(day, g):
        n = len(g)
        rng = np.random.default_rng([seed, int(str(day).replace("-", ""))])
        # range(1, n) not range(1, n-1): any bound that depends on the frame's
        # length is itself a peek at the day's length. backtest() already drops
        # triggers with no next bar to fill on.
        for i in range(1, n):
            if rng.random() < fire_prob:
                return [(i, 1 if rng.random() < 0.5 else -1)]
        return []
    return signal


# ---------------------------------------------------------------------------

def T1(bars):
    """The real bug. Lookahead ~1.74, honest ~1.0, verdict must be FAIL."""
    banner("T1 — NQ band fade (the strategy that faked PF 1.74)")
    sig = band_fade_signal(band=0.0027, start_min=540)
    v = audit(sig, bars, n_placebo=N_PLACEBO)
    v.report()

    ok = (v.lookahead_pf > 1.60 and v.honest_pf < 1.05 and not v.passed)
    print(f"\n  expected: lookahead ~1.74, honest ~1.0, verdict FAIL")
    print(f"  actual  : lookahead {v.lookahead_pf:.2f}, honest {v.honest_pf:.2f}, "
          f"verdict {'PASS' if v.passed else 'FAIL'}")
    return ok


def T2(bars):
    """A signal that reads the future. Must FAIL and be flagged as lookahead."""
    banner("T2 — planted lookahead (signal peeks at a future close)")
    sig = planted_lookahead_signal()

    # (a) audit must reject it and print the lookahead banner.
    #     Note: this cheat lives in the SIGNAL, so the fill-based checks cannot see
    #     it — with strict off it prints a gorgeous honest-looking PF ~1.7. It is
    #     audit's strict pass that catches it.
    v = audit(sig, bars, n_placebo=N_PLACEBO)
    v.report()
    flagged = (v.signal_leak is not None
               or (v.lookahead_gap is not None and v.lookahead_gap > 0.30))

    # (b) strict mode must refuse to run it at all
    try:
        backtest(sig, bars, fill="nextopen", strict=True)
        caught = False
    except AssertionError:
        caught = True
    print(f"\n  strict=True raised on the cheating signal: {caught}")

    ok = (not v.passed) and flagged and caught
    print(f"  expected: verdict FAIL + ⚠ LOOKAHEAD DETECTED + strict raises")
    print(f"  actual  : verdict {'PASS' if v.passed else 'FAIL'}, "
          f"flagged={flagged}, strict_caught={caught}")
    return ok


def T3(bars):
    """Pure noise. Must FAIL with honest PF near 1.0."""
    banner("T3 — pure random signal (coin-flip entries)")
    v = audit(random_signal(seed=42), bars, n_placebo=N_PLACEBO)
    v.report()

    ok = (not v.passed) and 0.70 < v.honest_pf < 1.20
    print(f"\n  expected: honest PF near 1.0, verdict FAIL")
    print(f"  actual  : honest {v.honest_pf:.2f}, "
          f"verdict {'PASS' if v.passed else 'FAIL'}")
    return ok


BAND_GRID = [0.0015, 0.002, 0.0025, 0.0027, 0.003, 0.0035, 0.004, 0.0045, 0.005]


def T5(bars):
    """
    Cherry-picked parameter. Must FAIL.

    This is the most common way a dead strategy gets published, and it is subtle
    enough that it beats the naive check: scan 9 band widths on NQ, keep the best
    one (0.0025), and report it. Gross of fees it prints PF 1.06 — over the
    honest-PF gate. Nothing is leaking. The number is real. It is still nothing:
    the whole grid sits in a flat noise field around 1.03, the edge is in-sample
    only, and the bootstrap CI straddles 1.0.

    If the harness passes this, the harness is useless, because this is what
    overfitting actually looks like in practice.
    """
    banner("T5 — cherry-picked parameter (best of a 9-band scan)")
    factory = lambda band: band_fade_signal(band=band, start_min=540)  # noqa: E731
    scan = overfit_scan(factory, bars, {"band": BAND_GRID})
    best = float(scan.loc[scan["pf"].idxmax(), "band"])
    print(f"  scanned {len(scan)} bands, best = {best} "
          f"(PF {scan['pf'].max():.3f}) -> now auditing ONLY that one\n")

    v = audit(factory(best), bars, n_placebo=N_PLACEBO,
              signal_factory=factory, grid={"band": BAND_GRID})
    v.report()

    print(f"\n  expected: verdict FAIL despite honest PF clearing 1.05")
    print(f"  actual  : honest {v.honest_pf:.2f}, "
          f"verdict {'PASS' if v.passed else 'FAIL'}")
    return (not v.passed) and v.honest_pf > 1.05


def T4():
    """A real, honestly-fillable edge. Must PASS — this is the positive control."""
    banner("T4 — synthetic REAL edge (positive control)")
    bars = synthetic_bars()
    sig = band_fade_signal(band=0.003, start_min=540)
    v = audit(sig, bars, n_placebo=N_PLACEBO, stop=0.0015, target=0.004)
    v.report()

    print(f"\n  expected: verdict PASS")
    print(f"  actual  : honest {v.honest_pf:.2f}, "
          f"verdict {'PASS' if v.passed else 'FAIL'}")
    return v.passed


def main():
    print("Loading NQ 5m bars...")
    bars = load_bars(NQ)
    print(f"  {len(bars)} days")

    results = {}
    for name, fn in (("T1", lambda: T1(bars)), ("T2", lambda: T2(bars)),
                     ("T3", lambda: T3(bars)), ("T5", lambda: T5(bars)),
                     ("T4", T4)):
        try:
            results[name] = fn()
        except Exception:
            traceback.print_exc()
            results[name] = False

    banner("SUMMARY")
    labels = {
        "T1": "NQ band fade        -> lookahead caught, verdict FAIL",
        "T2": "planted lookahead   -> verdict FAIL + flagged + strict raises",
        "T3": "pure random         -> honest PF ~1.0, verdict FAIL",
        "T5": "cherry-picked param -> verdict FAIL despite PF>1.05",
        "T4": "synthetic real edge -> verdict PASS",
    }
    for k in ("T1", "T2", "T3", "T5", "T4"):
        print(f"  [{'PASS' if results[k] else 'FAIL'}] {k}: {labels[k]}")

    all_ok = all(results.values())
    print()
    if all_ok:
        print("  ALL 5 SELF-TESTS PASS — the harness is trustworthy.")
    else:
        print("  SELF-TESTS FAILED — do not trust any number from this harness.")
    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
