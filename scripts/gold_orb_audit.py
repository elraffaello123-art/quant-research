"""
gold_orb_audit.py — the boring rule on the less efficient instrument.

WHY THIS, AFTER FIVE NULLS. Everything that has died in this project (gamma walls, 0DTE pin,
MR fade, order-book imbalance, options skew) was the same bet: an exotic signal predicting
NQ's next 5-60 minutes. That is the most contested game in finance. This inverts both halves
— a simple, well-understood rule on a thinner market (gold), where competition is lighter.

No options data here on purpose. Establish whether ANY structure exists in gold's price
first; only then is it worth adding GLD positioning as a filter. Bolting a filter onto a
signal that is already nothing is just a slower way to overfit.

THE RULE (plain English, so you can trace the code against it):
  - Take the first N bars of the RTH session as the "opening range".
  - MOMENTUM version: first close above the range high -> long. Below the low -> short.
  - FADE version: the mirror. First close above the range high -> SHORT.
  - One trade per day, first trigger only. Fill at the NEXT bar's open, always.

MGC bars are `m` = minutes since midnight EASTERN (570 = 09:30, 955 = 15:55), which is NOT
the same convention as nq_5m_all.pkl (that one is CENTRAL). Nothing here merges the two,
but don't copy this file's assumptions into one that does.

Run: python3 scripts/gold_orb_audit.py
"""
import sys

sys.path.insert(0, "toolkit")

from harness import audit, load_bars


def orb_signal(n_bars=6, fade=False):
    """Opening-range breakout on the first `n_bars` bars of the session.

    Careful with `strict=True`: the harness re-runs this on g.iloc[:i+1] to prove the
    trigger at bar i doesn't depend on future bars. So the opening range must come from
    the FIRST n_bars only (always available once i >= n_bars) and nothing may depend on
    the total length of the day.
    """
    def signal(day, g):
        hi = g["h"].iloc[:n_bars].max()      # range from the first n_bars only
        lo = g["l"].iloc[:n_bars].min()
        cl = g["c"].to_numpy()
        for i in range(n_bars, len(g)):
            if cl[i] > hi:
                return [(i, -1 if fade else +1)]      # one trade per day, first trigger
            if cl[i] < lo:
                return [(i, +1 if fade else -1)]
        return []
    return signal


def run(name, fade, stop, target):
    print("\n" + "#" * 72)
    print(f"#  {name}   stop={stop:.4f} target={target:.4f}")
    print("#" * 72)

    factory = lambda n_bars: orb_signal(n_bars=n_bars, fade=fade)
    # tick=0.10 is MGC. The harness DEFAULTS to 0.25 (NQ) — leaving it would make the
    # 1-tick stress line charge 2.5 ticks of slippage and understate the strategy by ~0.10 PF.
    # Any instrument that isn't NQ must pass its own tick.
    v = audit(
        factory(6), bars,
        stop=stop, target=target, one_per_day=True, tick=0.10,
        signal_factory=factory,
        grid={"n_bars": [3, 6, 9, 12, 18]},   # 15/30/45/60/90 min opening ranges
    )
    v.report()
    return v


if __name__ == "__main__":
    # min_bars filters short/holiday sessions at LOAD time. Doing it inside the signal
    # would depend on the day's total length, which is future information at bar 7 and
    # strict=True would (correctly) reject it.
    bars = load_bars("data/pkl/mgc_5m.pkl", min_bars=60)
    print(f"MGC: {len(bars)} days loaded")

    # Gold's daily sd is ~1.1%, so an intraday stop of ~0.3% with a 2:1 target is the
    # neutral starting point — NOT a tuned choice. The grid scan below is what decides
    # whether any of this survives nudging the knobs.
    run("GOLD ORB — MOMENTUM", fade=False, stop=0.003, target=0.006)
    run("GOLD ORB — FADE",     fade=True,  stop=0.003, target=0.006)
