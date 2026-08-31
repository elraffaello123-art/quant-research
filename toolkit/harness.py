"""
harness.py — the leak-proof backtest harness.

THE ONE LAW
-----------
A strategy decides on bar `i` using ONLY data from bars 0..i.
The harness fills the entry at bar `i+1`'s OPEN.

There is no "fill at the level". If you want the old lookahead fill you must pass
allow_lookahead=True, and the harness screams at you and marks the result UNTRUSTED.

Why: on 2026-07-20 a band-fade printed profit factor 1.74, "positive every year".
The signal filled at the band level on the trigger bar, but only kept trades where
that same bar CLOSED back inside the band. You cannot know the close while a resting
order is filling mid-bar — so the code was silently deleting the losers with hindsight.
Filled honestly at the next bar's open the same rule is ~1.0. No edge.

WHAT THIS HARNESS TRIES TO DO TO YOUR STRATEGY
----------------------------------------------
It is not a backtester. It is a machine for FALSIFYING a backtest. It attacks the
result from five independent directions, and a strategy has to survive all of them:

    lookahead   next-open fills, the level-fill gap, and strict signal replay
    placebo     random entries and shuffled levels through the same exit engine
    luck        bootstrap confidence interval on PF, trade-count adequacy
    overfit     out-of-sample split, parameter plateau scan
    fragility   concentration (drop the best trades), 1-tick stress, regimes

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
No costs (cost=0.0, slippage_ticks=0) and no drawdown/ruin model. This is prop-firm
research: ~$5 round-turn is noise against the trade, and account survival is a
POSITION SIZING question, not an edge question. Gating on drawdown would fail a
strategy for being sized wrong, which is a different bug than not having an edge.
Size it after you believe it.

The 1-tick line in the report is a thinness gauge — how much edge survives contact
with a tick of reality — and it is REPORTED, NOT GATED.

WHAT A STRATEGY LOOKS LIKE
--------------------------
A strategy is just a function:

    def signal(day: str, g: DataFrame) -> list[tuple]

returning triggers. Each trigger is either
    (i, direction)            -- bar index i, direction +1 long / -1 short
    (i, direction, level)     -- same, plus the price level it triggered on
                                 (only needed if you want to MEASURE the lookahead)

The rule the signal must obey: when deciding about bar i, look only at g.iloc[:i+1].
strict=True (on by default in audit) re-runs your signal on truncated data to verify.

Everything here is plain pandas and meant to be read line by line.
"""

import itertools
import os
from collections import namedtuple

import numpy as np
import pandas as pd


# One trade, fully inspectable. Read these — auditing individual trades is how you
# catch a strategy that backtests fine but isn't the strategy you described.
Trade = namedtuple(
    "Trade", "day year i direction entry exit ret bars_held"
)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_bars(path, min_bars=40):
    """
    Load a pkl of bars with columns d,m,o,h,l,c and return {day_str: DataFrame}.

    d = day string 'YYYY-MM-DD', m = minutes since midnight (CENTRAL tz for NQ),
    o/h/l/c = the bar. Each day's frame is sorted by m and re-indexed 0..n-1 so
    that "bar i" means the same thing everywhere in this file.

    min_bars drops short days (half sessions, holidays, bad data) at LOAD time.

    Why here and not inside your signal: "how many bars this day ends up having" is
    a property of the whole day. A signal that checks it is deciding bar i using
    information from after bar i — a (mild, real) lookahead, and strict=True will
    correctly flag it. Keeping the filter out here makes it a universe/data-quality
    decision applied uniformly before any strategy runs. Be aware it is still a
    survivorship-flavoured choice; set min_bars=0 to disable it.
    """
    df = pd.read_pickle(path)
    for col in ("d", "m", "o", "h", "l", "c"):
        if col not in df.columns:
            raise ValueError(f"{path} is missing column '{col}'")
    bars = {}
    for day, g in df.groupby("d"):
        if len(g) < min_bars:
            continue
        bars[day] = g.sort_values("m").reset_index(drop=True)
    return bars


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def rets(trades):
    """Pull the return series out of a list of Trades."""
    return [t.ret if isinstance(t, Trade) else t for t in trades]


def PF(returns):
    """Profit factor = gross wins / gross losses. >1 makes money, <1 loses."""
    r = np.asarray(rets(list(returns)), float)
    if r.size == 0:
        return float("nan")
    wins = r[r > 0].sum()
    losses = -r[r < 0].sum()
    return wins / losses if losses > 0 else float("inf")


def per_year(trades):
    """{year: PF} from a list of Trades."""
    by = {}
    for t in trades:
        by.setdefault(t.year, []).append(t.ret)
    return {y: round(PF(v), 2) for y, v in sorted(by.items())}


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

def backtest(signal, bars, *, stop=0.0015, target=0.004, cost=0.0,
             fill="nextopen", slippage_ticks=0, tick=0.25, one_per_day=True,
             allow_lookahead=False, strict=False, max_hold=None, exit_by=None):
    """
    Run `signal` over `bars` and return a list of Trade.

    fill='nextopen'  HONEST, the default. Entry fills at bar i+1's OPEN.
                     Bar i's close/high/low NEVER touch the entry price.
    fill='atlevel'   UNTRUSTED. Entry fills at the level the signal reports on bar i.
                     Requires 3-tuple triggers AND allow_lookahead=True. This exists
                     only so audit() can measure how big a lie the level-fill is.

    Exits, in this order each bar (conservative — stop is checked BEFORE target):
      1. stop hit?   long: low <= stop / short: high >= stop.
                     If the bar OPENED already beyond the stop we fill at the open
                     (gap-fill), not at the stop price.
      2. target hit? long: high >= target / short: low <= target. Filled at the
                     target price — a limit order that gaps through fills at your
                     price or better.
      3. otherwise carry to the last bar of the day and exit at its close.

    cost             round-trip cost as a fraction. DEFAULT 0.0 (prop-firm gross).
    slippage_ticks   applied ADVERSELY at entry, stop exits and EOD exits; never at
                     the target. DEFAULT 0. Used by the fragility diagnostic.
    one_per_day      keep only the first trigger of each day.
    max_hold         exit at market after this many bars if neither stop nor target
                     hit. None = carry to the day's close (the original behaviour).
    exit_by          ABSOLUTE bar index: force the exit at or before this bar of the
                     session, regardless of when the trade was entered. max_hold is
                     relative to the trigger; exit_by is wall-clock. Added 2026-08-20
                     for the HarvestPremia ORB, whose spec says "close at 10:30 ET
                     regardless" -- a fixed clock time, not a fixed holding period.
                     Combine freely: the earlier of the two wins.

    stop/target      a float, OR a callable f(day) -> float for per-session sizing.
                     Added 2026-07-21 for the GC/SI/CL vol scan: median 5-min vol is
                     0.059% on gold and 0.152% on oil, so one fixed fraction is a
                     normal stop on one instrument and inside a single bar on another.
                     Cross-instrument comparison needs stops that mean the same thing,
                     i.e. scaled to each session's own ATR. The callable is evaluated
                     ONCE PER DAY from data strictly before that session — it must not
                     look at the session it sizes.
    strict           anti-cheat: re-run the signal on g.iloc[:i+1] and assert the
                     trigger still fires. See _check_strict.
    """
    if fill not in ("nextopen", "atlevel"):
        raise ValueError("fill must be 'nextopen' or 'atlevel'")
    if fill == "atlevel" and not allow_lookahead:
        raise ValueError(
            "fill='atlevel' is LOOKAHEAD and requires allow_lookahead=True. "
            "The honest fill is 'nextopen'."
        )
    if fill == "atlevel":
        print("⚠ WARNING: fill='atlevel' — this result is UNTRUSTED lookahead, "
              "not a tradeable number.")

    slip = slippage_ticks * tick
    trades = []

    for day, g in bars.items():
        n = len(g)
        if n < 3:
            continue

        triggers = signal(day, g)
        if not triggers:
            continue

        # per-session exit sizing, resolved once per day (see docstring)
        stop_d = float(stop(day)) if callable(stop) else stop
        targ_d = float(target(day)) if callable(target) else target
        if not (stop_d > 0 and targ_d > 0):
            continue                                 # no ATR yet (warmup) -> no trade
        triggers = sorted(triggers, key=lambda t: t[0])
        if one_per_day:
            triggers = triggers[:1]

        # numpy views: faster and makes the index arithmetic obvious
        op = g["o"].to_numpy()
        hi = g["h"].to_numpy()
        lo = g["l"].to_numpy()
        cl = g["c"].to_numpy()

        for trig in triggers:
            i, edir = trig[0], trig[1]
            level = trig[2] if len(trig) > 2 else None
            if edir not in (1, -1):
                raise ValueError(f"direction must be +1 or -1, got {edir}")

            if strict:
                _check_strict(signal, day, g, i, edir)

            # ---------- ENTRY FILL: this is where fake edges are born ----------
            if fill == "nextopen":                      # <-- HONEST
                if i + 1 >= n:
                    continue                            # no next bar, no trade
                ent = op[i + 1] + edir * slip           # pay up to get in
                scan_from = i + 1                       # entry bar can stop us out
            else:                                       # <-- LOOKAHEAD
                if level is None:
                    raise ValueError(
                        "fill='atlevel' needs the signal to return (i, dir, level)"
                    )
                ent = float(level)
                scan_from = i + 1

            st = ent * (1 - edir * stop_d)              # stop is against the trade
            tp = ent * (1 + edir * targ_d)              # target is with the trade

            last = n - 1 if max_hold is None else min(n - 1, i + max_hold)
            if exit_by is not None:
                last = min(last, int(exit_by))
            if last < scan_from:
                continue                            # cutoff precedes the fill

            ex, k_exit = None, last
            for k in range(scan_from, last + 1):
                if edir > 0:
                    if lo[k] <= st:                     # stop first: conservative
                        ex, k_exit = min(st, op[k]) - slip, k
                        break
                    if hi[k] >= tp:
                        ex, k_exit = tp, k              # limit fills at our price
                        break
                else:
                    if hi[k] >= st:
                        ex, k_exit = max(st, op[k]) + slip, k
                        break
                    if lo[k] <= tp:
                        ex, k_exit = tp, k
                        break
            if ex is None:                              # timed out / flat at close
                ex = cl[last] - edir * slip

            trades.append(Trade(
                day=str(day), year=int(str(day)[:4]), i=i, direction=edir,
                entry=float(ent), exit=float(ex),
                ret=edir * (ex - ent) / ent - cost,
                bars_held=k_exit - i,
            ))

    return trades


def _check_strict(signal, day, g, i, edir):
    """
    Anti-cheat. Re-run the signal on ONLY bars 0..i and assert the same trigger
    still fires. A signal that needs to see bars after i to know it should fire on
    bar i is looking at the future — this raises instead of quietly producing a
    beautiful, fake equity curve.

    GOTCHA: any condition that depends on the LENGTH of the frame it was handed
    will trip this — correctly, because the day's total length is itself future
    information at bar 7. See toolkit/README.md.
    """
    truncated = g.iloc[:i + 1].reset_index(drop=True)
    again = signal(day, truncated)
    if not any(t[0] == i and t[1] == edir for t in (again or [])):
        raise AssertionError(
            f"LEAK: signal fired (bar {i}, dir {edir}) on {day} with the full day "
            f"visible, but NOT when it could only see bars 0..{i}. "
            f"It is using future bars to decide."
        )


# ---------------------------------------------------------------------------
# Falsification battery — luck, overfit, fragility, ruin
# ---------------------------------------------------------------------------

def bootstrap_pf(trades, n_boot=2000, seed=0, pct=5):
    """
    IS IT LUCK? Resample the trades with replacement and return the `pct`-th
    percentile of the resulting PF distribution.

    A PF of 1.30 on 60 trades and a PF of 1.30 on 2000 trades are not the same
    claim. This puts an error bar on the number. If the 5th percentile is below
    1.0, you cannot distinguish your edge from noise — regardless of how good the
    headline looks.
    """
    r = np.asarray(rets(trades), float)
    if r.size < 2:
        return float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, r.size, size=(n_boot, r.size))
    samp = r[idx]
    wins = np.where(samp > 0, samp, 0.0).sum(axis=1)
    loss = -np.where(samp < 0, samp, 0.0).sum(axis=1)
    pfs = np.where(loss > 0, wins / np.where(loss > 0, loss, 1.0), np.inf)
    return float(np.percentile(pfs[np.isfinite(pfs)], pct))


def concentration_pf(trades, drop_frac=0.01, min_drop=5):
    """
    IS IT A HANDFUL OF TRADES? Delete the biggest winners and recompute PF.

    A real edge is a tax on many trades. A mirage is three monster days in 2020
    carrying a thousand mediocre ones. If dropping the top 1% flips you below 1.0,
    you do not have a strategy, you have a lottery ticket you already scratched.
    """
    r = sorted(rets(trades), reverse=True)
    k = max(min_drop, int(len(r) * drop_frac))
    if len(r) <= k:
        return float("nan")
    return PF(r[k:])


def oos_split_pf(trades, frac=0.70):
    """
    IS IT OVERFIT? Split the trades chronologically and compare.

    Every threshold you picked (band width, stop, target, session filter) was
    chosen while looking at this data. The last 30% is the closest thing to a
    holdout you have left. If the edge lives only in the first 70%, you fitted
    the past.
    """
    ts = sorted(trades, key=lambda t: t.day)
    cut = int(len(ts) * frac)
    if cut < 2 or len(ts) - cut < 2:
        return float("nan"), float("nan")
    return PF(ts[:cut]), PF(ts[cut:])


def regime_split_pf(trades, bars):
    """
    DOES IT NEED ONE WEATHER? Split trades by the day's realized range (a cheap
    volatility proxy) at the median and score each half.

    Reported, not gated — plenty of honest edges are volatility-dependent. But you
    should know which one you have before you size it.
    """
    vol = {}
    for d, g in bars.items():
        ref = g["c"].iloc[0]
        vol[d] = (g["h"].max() - g["l"].min()) / ref if ref else np.nan
    v = [vol.get(t.day, np.nan) for t in trades]
    if not v or np.all(np.isnan(v)):
        return float("nan"), float("nan")
    med = np.nanmedian(v)
    lo = [t for t in trades if vol.get(t.day, np.nan) < med]
    hi = [t for t in trades if vol.get(t.day, np.nan) >= med]
    return PF(lo), PF(hi)


def side_split_pf(trades):
    """
    IS IT JUST DIRECTION? PF of longs vs shorts, reported separately.

    An edge that is entirely short on an index that rose for a decade is usually a
    short-vol artifact; an edge that is entirely long may just be beta. Reported,
    not gated — one-sided edges can be real.
    """
    return (PF([t for t in trades if t.direction > 0]),
            PF([t for t in trades if t.direction < 0]))


def overfit_scan(signal_factory, bars, grid, **params):
    """
    IS THE PARAMETER CHOICE A SPIKE OR A PLATEAU?

    signal_factory(**kwargs) -> signal. grid = {param: [values...]}.
    Runs the honest backtest over the whole cartesian product.

    The logic: if your rule is real, it should still work when you nudge the knobs.
    An edge that exists at band=0.0027 but dies at 0.0025 and 0.0029 is a fit to
    noise. We therefore care about the MEDIAN of the grid, not the best cell —
    reporting the best cell of a 40-cell scan as "the" result is how PFs get
    manufactured. Returns a DataFrame, one row per combination.
    """
    params.pop("fill", None)
    params.pop("allow_lookahead", None)
    keys = list(grid)
    rows = []
    for combo in itertools.product(*[grid[k] for k in keys]):
        kw = dict(zip(keys, combo))
        tr = backtest(signal_factory(**kw), bars, fill="nextopen", **params)
        rows.append({**kw, "pf": PF(tr), "n_trades": len(tr)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Placebos
# ---------------------------------------------------------------------------

def _returns_signal_levels(signal, bars, probe_days=50):
    """Does this signal report levels (3-tuples)? Probe a few days to find out."""
    for day in list(bars)[:probe_days]:
        for trig in (signal(day, bars[day]) or []):
            return len(trig) > 2
    return False


def random_entry_signal(signal, bars, seed):
    """
    PLACEBO #1 — the exit machinery test (LEAK_CHECKLIST #2).

    On every day the real signal traded, enter at a RANDOM bar in a RANDOM
    direction — then run through the SAME exit logic. Same days, same number of
    trades, same stops and targets; only the timing and side are destroyed.

    If this also prints a good PF, your EXITS are the artifact, not your signal.
    """
    fired = set()
    for day, g in bars.items():
        if signal(day, g):
            fired.add(day)

    def sig(day, g):
        # rng seeded per (seed, day) so the placebo is reproducible run to run
        # rather than depending on dict iteration order.
        if day not in fired or len(g) < 3:
            return []
        rng = np.random.default_rng([seed, int(str(day).replace("-", ""))])
        i = int(rng.integers(1, max(2, len(g) - 1)))
        return [(i, 1 if rng.random() < 0.5 else -1)]
    return sig


def _placebo_pfs(make_signal, bars, n_placebo, params):
    """Run n_placebo randomized variants and return their PFs."""
    pfs = []
    for seed in range(n_placebo):
        trades = backtest(make_signal(seed), bars, fill="nextopen", **params)
        pfs.append(PF(trades))
    return [p for p in pfs if np.isfinite(p)]


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------

class Verdict:
    """
    The result of audit(). Holds every number and the pass/fail reasoning.

    Read `passed` and `reasons`; call `report()` to print the whole story with the
    honest number first and biggest.
    """

    @classmethod
    def from_signal_leak(cls, message):
        """
        The signal itself reads the future — strict=True caught it.

        This is a DIFFERENT bug from the fill lookahead, and it is worse. Honest
        fills cannot save a contaminated signal: if the rule already knows the
        answer, filling at the next open just collects the same stolen edge one bar
        later. There is no number to report here, so we don't compute one.
        """
        v = cls.__new__(cls)
        v.signal_leak = message
        v.honest_pf = float("nan")
        v.honest_trades = []
        v.lookahead_pf = None
        v.random_pfs = []
        v.shuffle_pfs = None
        v.years = {}
        v.n_trades = 0
        v.random_p75 = float("nan")
        v.shuffle_p75 = None
        v.year_frac = 0.0
        v.d = {}
        v.scan = None
        v.checks = [("signal does not peek ahead", False, message.split("\n")[0])]
        v.passed = False
        v.reasons = [f"signal does not peek ahead: {message}"]
        return v

    def __init__(self, honest_pf, honest_trades, lookahead_pf, random_pfs,
                 shuffle_pfs, years, n_trades, diagnostics, scan=None):
        self.signal_leak = None
        self.honest_pf = honest_pf
        self.honest_trades = honest_trades
        self.lookahead_pf = lookahead_pf          # None if no levels reported
        self.random_pfs = random_pfs
        self.shuffle_pfs = shuffle_pfs            # None if no level_shuffler given
        self.years = years
        self.n_trades = n_trades
        self.d = diagnostics                      # everything from the battery
        self.scan = scan                          # overfit_scan DataFrame or None

        self.random_p75 = float(np.percentile(random_pfs, 75)) if random_pfs else float("nan")
        self.shuffle_p75 = (float(np.percentile(shuffle_pfs, 75))
                            if shuffle_pfs else None)
        pos = [y for y, p in years.items() if p > 1.0]
        self.year_frac = len(pos) / len(years) if years else 0.0

        self.checks = []          # (name, passed, detail)
        self._evaluate()
        self.passed = all(ok for _, ok, _ in self.checks)
        self.reasons = [f"{name}: {detail}" for name, ok, detail in self.checks if not ok]

    def _evaluate(self):
        add = self.checks.append
        d = self.d

        # --- is there anything there at all ---
        add(("honest PF > 1.05",
             self.honest_pf > 1.05,
             f"honest_pf={self.honest_pf:.2f}"))

        add(("enough trades (>=100)",
             self.n_trades >= 100,
             f"n={self.n_trades}"))

        # --- is it better than nothing ---
        add(("beats random entry (p75)",
             self.honest_pf > self.random_p75,
             f"honest_pf={self.honest_pf:.2f} vs random p75={self.random_p75:.2f}"))

        if self.shuffle_p75 is not None:
            add(("beats shuffled levels (p75)",
                 self.honest_pf > self.shuffle_p75,
                 f"honest_pf={self.honest_pf:.2f} vs shuffle p75={self.shuffle_p75:.2f}"))

        # --- is it luck ---
        add(("bootstrap 5th pct PF > 1.0",
             d["boot_p5"] > 1.0,
             f"5th pct={d['boot_p5']:.2f} (headline {self.honest_pf:.2f})"))

        # --- is it a plateau in time ---
        add((">=60% of years PF>1",
             self.year_frac >= 0.60,
             f"{self.year_frac:.0%} of {len(self.years)} years positive"))

        # --- is it overfit ---
        add(("out-of-sample (last 30%) PF > 1.0",
             d["oos_pf"] > 1.0,
             f"in-sample={d['is_pf']:.2f} out-of-sample={d['oos_pf']:.2f}"))

        # --- is it a handful of trades ---
        add(("survives dropping top 1% of trades",
             d["conc_pf"] > 1.0,
             f"PF without best trades={d['conc_pf']:.2f}"))

        # --- parameter plateau, only if a grid was scanned ---
        if self.scan is not None and len(self.scan):
            pf = self.scan["pf"].replace([np.inf, -np.inf], np.nan).dropna()
            frac = float((pf > 1.0).mean()) if len(pf) else 0.0
            # The bar is 1.05, the SAME bar the headline has to clear — not 1.0.
            # A grid hovering at 1.02 is not a plateau, it is a flat noise field
            # that happens to lean positive, and cherry-picking its best cell is
            # exactly how a dead strategy gets published.
            add(("parameter plateau, not a spike",
                 float(pf.median()) > 1.05 and frac >= 0.60,
                 f"median of {len(pf)} combos={pf.median():.2f}, "
                 f"{frac:.0%} positive, best={pf.max():.2f}"))

        # --- the 2026-07-20 bug, encoded as a hard rule ---
        if self.lookahead_pf is not None:
            leaked = self.lookahead_pf > 1.30 and self.honest_pf < 1.05
            add(("edge is not just the lookahead",
                 not leaked,
                 f"lookahead_pf={self.lookahead_pf:.2f} but honest_pf={self.honest_pf:.2f}"))

    @property
    def lookahead_gap(self):
        if self.lookahead_pf is None:
            return None
        return self.lookahead_pf - self.honest_pf

    def report(self):
        if self.signal_leak:
            print("=" * 72)
            print("  ⚠ LOOKAHEAD DETECTED IN THE SIGNAL ITSELF")
            print("=" * 72)
            for line in self.signal_leak.split("\n"):
                print(f"    {line.strip()}")
            print()
            print("    No PF is reported, because every number this strategy could")
            print("    produce would be built on information it could not have had.")
            print("    Honest fills do NOT fix this — fix the signal.")
            print()
            print("  VERDICT: FAIL")
            print("=" * 72)
            return False

        d = self.d
        print("=" * 72)
        print(f"  HONEST PF (next-open fills, gross)  : {self.honest_pf:.2f}"
              f"     n={self.n_trades}")
        print("=" * 72)
        print(f"  per-year (honest): {self.years}")
        print()
        print("  -- luck & overfit ------------------------------------------------")
        print(f"  bootstrap PF 90% CI      : [{d['boot_p5']:.2f}, {d['boot_p95']:.2f}]")
        print(f"  in-sample / out-of-sample: {d['is_pf']:.2f} / {d['oos_pf']:.2f}")
        print(f"  PF w/o top 1% of trades  : {d['conc_pf']:.2f}")
        if self.scan is not None and len(self.scan):
            pf = self.scan["pf"].replace([np.inf, -np.inf], np.nan).dropna()
            print(f"  parameter scan ({len(pf)} combos) : median={pf.median():.2f} "
                  f"best={pf.max():.2f} worst={pf.min():.2f} "
                  f"{float((pf > 1.0).mean()):.0%} positive")
        print()
        print("  -- placebos ------------------------------------------------------")
        if self.random_pfs:
            print(f"  random-entry placebo     : median={np.median(self.random_pfs):.2f} "
                  f"p75={self.random_p75:.2f}")
        if self.shuffle_pfs:
            print(f"  shuffled-level placebo   : median={np.median(self.shuffle_pfs):.2f} "
                  f"p75={self.shuffle_p75:.2f}")
        print()
        print("  -- fragility & regime --------------------------------------------")
        print(f"  low-vol / high-vol days  : {d['vol_lo']:.2f} / {d['vol_hi']:.2f}")
        print(f"  long / short             : {d['long_pf']:.2f} / {d['short_pf']:.2f}")
        print(f"  1-tick stress (FYI only) : {d['slip1_pf']:.2f}   "
              f"<- not a cost model, a thinness gauge")
        print()
        for name, ok, detail in self.checks:
            print(f"    [{'PASS' if ok else 'FAIL'}] {name:<34} {detail}")
        print()

        # Never print the lookahead number without the warning attached.
        if self.lookahead_pf is not None and self.lookahead_gap > 0.30:
            print(f"  ⚠ LOOKAHEAD DETECTED: the level-fill number "
                  f"({self.lookahead_pf:.2f}) is a lie, honest = {self.honest_pf:.2f}")
            print(f"    gap = {self.lookahead_gap:.2f} PF. Filling at the level lets the")
            print(f"    strategy use information it could not have had at fill time.")
            print()

        print(f"  VERDICT: {'PASS' if self.passed else 'FAIL'}")
        if not self.passed:
            for r in self.reasons:
                print(f"    - {r}")
        print("=" * 72)
        return self.passed


# ---------------------------------------------------------------------------
# audit()
# ---------------------------------------------------------------------------

def audit(signal, bars, *, level_shuffler=None, n_placebo=20, strict=True,
          signal_factory=None, grid=None, **params):
    """
    THE function. Run the full falsification battery and return a Verdict.

    signal          your strategy, see the module docstring.
    level_shuffler  optional factory `f(rng) -> signal` that rebuilds your strategy
                    on SHUFFLED/JITTERED levels. If the real levels don't clearly
                    beat these fakes, the level carries no information.
    n_placebo       how many random seeds per placebo.
    strict          re-verify every trigger against truncated data. ON BY DEFAULT.
                    There are TWO kinds of lookahead and they need different traps:
                      - lookahead in the FILL   -> caught by next-open fills + the gap
                      - lookahead in the SIGNAL -> caught ONLY by this
                    A signal that peeks at a future bar sails through every
                    fill-based check with a beautiful PF. Don't turn this off.
    signal_factory  + grid: run the parameter-plateau scan. factory(**kw) -> signal,
                    grid = {param: [values]}. Without these the overfit scan is
                    skipped and that check simply doesn't run.
    **params        passed to backtest(): stop, target, cost, tick, one_per_day...

    Nothing here reports a PF that wasn't produced by the one shared exit engine.
    """
    params.pop("fill", None)
    params.pop("allow_lookahead", None)
    params.pop("slippage_ticks", None)

    # 1. the honest number — the only one that counts.
    #    If strict catches the signal reading the future, we stop here: a
    #    contaminated signal has no honest number to report.
    try:
        honest = backtest(signal, bars, fill="nextopen", strict=strict, **params)
    except AssertionError as e:
        return Verdict.from_signal_leak(str(e))

    if len(honest) < 2:
        return Verdict.from_signal_leak(
            f"signal produced only {len(honest)} trades — nothing to audit."
        )

    honest_pf = PF(honest)

    # 2. the lookahead number, only if the signal reports levels — for the GAP
    lookahead_pf = None
    if _returns_signal_levels(signal, bars):
        look = backtest(signal, bars, fill="atlevel", allow_lookahead=True, **params)
        lookahead_pf = PF(look)

    # 3. random entries through the same exits
    random_pfs = _placebo_pfs(
        lambda s: random_entry_signal(signal, bars, s), bars, n_placebo, params)

    # 4. shuffled levels
    shuffle_pfs = None
    if level_shuffler is not None:
        shuffle_pfs = _placebo_pfs(
            lambda s: level_shuffler(np.random.default_rng(1000 + s)), bars,
            n_placebo, params)

    # 5. the falsification battery
    is_pf, oos_pf = oos_split_pf(honest)
    vol_lo, vol_hi = regime_split_pf(honest, bars)
    long_pf, short_pf = side_split_pf(honest)
    slip1 = backtest(signal, bars, fill="nextopen", slippage_ticks=1, **params)

    diagnostics = {
        "boot_p5": bootstrap_pf(honest, pct=5),
        "boot_p95": bootstrap_pf(honest, pct=95),
        "conc_pf": concentration_pf(honest),
        "is_pf": is_pf, "oos_pf": oos_pf,
        "vol_lo": vol_lo, "vol_hi": vol_hi,
        "long_pf": long_pf, "short_pf": short_pf,
        "slip1_pf": PF(slip1),
    }

    # 6. parameter plateau
    scan = None
    if signal_factory is not None and grid:
        scan = overfit_scan(signal_factory, bars, grid, **params)

    return Verdict(honest_pf, honest, lookahead_pf, random_pfs, shuffle_pfs,
                   per_year(honest), len(honest), diagnostics, scan)


# ---------------------------------------------------------------------------
# Strategies used by the self-tests
# ---------------------------------------------------------------------------

def band_fade_signal(band=0.0027, start_min=540):
    """
    The strategy that produced the fake 1.74, written as a proper signal.

    On each bar after start_min: if the high tagged open*(1+band) and the bar
    CLOSED BACK BELOW the band -> short (fade the failed break). Mirror for longs.

    Note the close is legitimate INPUT here — you know bar i's close at the end of
    bar i. The lie was never the signal; it was filling at the band price, which
    happened mid-bar, before that close existed. That is exactly what this harness
    makes impossible.
    """
    def signal(day, g):
        n = len(g)
        ref = g["c"].iloc[0]                    # first bar's close = session open
        upper, lower = ref * (1 + band), ref * (1 - band)
        m = g["m"].to_numpy()
        hi, lo, cl = g["h"].to_numpy(), g["l"].to_numpy(), g["c"].to_numpy()
        out = []
        for i in range(1, n):
            if m[i] < start_min:
                continue
            if hi[i] >= upper and cl[i] < upper:
                out.append((i, -1, upper))
            elif lo[i] <= lower and cl[i] > lower:
                out.append((i, 1, lower))
        return out
    return signal


def band_fade_shuffler(rng):
    """
    Level shuffler for the band fade: rebuild the strategy on a RANDOM band width
    instead of the tuned 0.27%. If 0.27% carries real information, it should beat
    these. (For an options strategy this is where you'd shuffle OI across strikes.)
    """
    return band_fade_signal(band=float(rng.uniform(0.0010, 0.0050)))


def planted_lookahead_signal(start_min=540, lookforward=3):
    """
    A DELIBERATELY CHEATING signal, used to prove strict=True catches cheaters.

    It fires only when the close `lookforward` bars in the FUTURE is lower than the
    current close — i.e. it already knows the trade wins. Run without strict this
    prints a gorgeous fake PF. Run with strict=True it must raise.
    """
    def signal(day, g):
        n = len(g)
        m = g["m"].to_numpy()
        cl = g["c"].to_numpy()
        out = []
        for i in range(1, n):
            if m[i] < start_min:
                continue
            j = i + lookforward
            if j >= n:                       # can't peek past the data we were given
                continue
            if cl[j] < cl[i]:                # <-- THE CHEAT: reading the future
                out.append((i, -1, cl[i]))
        return out
    return signal


def synthetic_bars(n_days=1250, bars_per_day=78, seed=7, kappa=0.20,
                   sigma=0.0008, start_year=2019, price0=4000.0):
    """
    Random-walk 5-min days with a GENUINE mean-reversion injected.

    This is the harness's positive control. A harness that fails everything is
    useless — we need to know it can still say YES to a real edge, otherwise "FAIL"
    carries no information.

    The injected truth: each bar drifts back toward the session open in proportion
    to how far it has strayed (an Ornstein-Uhlenbeck pull, strength `kappa`).
    So after a +0.3% move, price really does tend to come back — and it is still
    there when you fill at the NEXT BAR'S OPEN. No lookahead is required to collect it.

    Note on honesty: `kappa` was chosen large enough that the edge is detectable
    above the noise. That is calibrating a test fixture with a known answer, which
    is legitimate — it is NOT the same as tuning a real strategy until it passes.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_days):
        year = start_year + d // 250
        day = f"{year}-{1 + (d % 250) // 21:02d}-{1 + (d % 21):02d}"
        px = price0 * float(np.exp(rng.normal(0, 0.02)))   # each day opens somewhere
        open_px = px
        prev = px
        for b in range(bars_per_day):
            dev = px / open_px - 1.0                       # how far we've strayed
            drift = -kappa * dev                           # ...and the pull back
            px = px * (1.0 + drift + sigma * rng.normal())
            o, c = prev, px
            wick = abs(sigma * rng.normal()) * o
            rows.append({
                "d": day, "m": 510 + 5 * b, "o": o,
                "h": max(o, c) + wick, "l": min(o, c) - wick, "c": c,
            })
            prev = px
    df = pd.DataFrame(rows)
    return {day: g.sort_values("m").reset_index(drop=True)
            for day, g in df.groupby("d")}


# ---------------------------------------------------------------------------
# Phase self-tests
# ---------------------------------------------------------------------------

def _nq():
    here = os.path.dirname(os.path.abspath(__file__))
    return load_bars(os.path.join(here, "..", "data", "pkl", "nq_5m_all.pkl"))


def _self_test_phase1():
    bars = _nq()
    print(f"loaded {len(bars)} days of NQ 5m bars")
    sig = band_fade_signal(band=0.0027, start_min=540)
    look = backtest(sig, bars, fill="atlevel", allow_lookahead=True)
    hon = backtest(sig, bars, fill="nextopen")
    pf_look, pf_hon = PF(look), PF(hon)
    print(f"  fill AT LEVEL (lookahead, UNTRUSTED): PF={pf_look:.2f}  n={len(look)}")
    print(f"  fill NEXT OPEN (honest)             : PF={pf_hon:.2f}  n={len(hon)}")
    print(f"  per-year (honest): {per_year(hon)}")
    ok = pf_look > 1.5 and pf_hon < 1.15 and pf_hon < pf_look - 0.4
    print(f"\nPhase 1 self-test: {'PASS' if ok else 'FAIL'}")
    return ok


def _self_test_phase2():
    bars = _nq()
    sig = band_fade_signal(band=0.0027, start_min=540)
    print("\naudit() on the NQ band fade — the strategy that faked 1.74:\n")
    v = audit(sig, bars, level_shuffler=band_fade_shuffler, n_placebo=10)
    v.report()
    ok = (not v.passed) and v.lookahead_pf > 1.5 and v.honest_pf < 1.05
    print(f"\nPhase 2 self-test: {'PASS' if ok else 'FAIL'}")
    return ok


def _self_test_phase3():
    bars = _nq()
    small = {d: bars[d] for d in list(bars)[:200]}
    clean = band_fade_signal(band=0.0027, start_min=540)
    try:
        backtest(clean, small, fill="nextopen", strict=True)
        a_ok = True
        print("  (a) band_fade under strict=True: no leak raised   -> PASS")
    except AssertionError as e:
        a_ok = False
        print(f"  (a) band_fade under strict=True: unexpectedly raised: {e}  -> FAIL")

    cheat = planted_lookahead_signal()
    try:
        backtest(cheat, small, fill="nextopen", strict=True)
        b_ok = False
        print("  (b) planted-lookahead under strict=True: NOT caught  -> FAIL")
    except AssertionError as e:
        b_ok = True
        print("  (b) planted-lookahead under strict=True: caught -> PASS")
        print(f"      {str(e)[:110]}...")

    fake = backtest(cheat, small, fill="nextopen")
    print(f"  (c) same cheating signal WITHOUT strict: PF={PF(fake):.2f}"
          f"  <- this is what a leak looks like")
    ok = a_ok and b_ok
    print(f"\nPhase 3 self-test: {'PASS' if ok else 'FAIL'}")
    return ok


def _self_test_phase4():
    bars = synthetic_bars()
    print(f"  synthetic: {len(bars)} days with a real, honestly-fillable "
          f"mean-reversion injected")
    v = audit(band_fade_signal(band=0.003, start_min=540), bars, n_placebo=10,
              stop=0.0015, target=0.004,
              signal_factory=lambda band: band_fade_signal(band=band, start_min=540),
              grid={"band": [0.002, 0.0025, 0.003, 0.0035, 0.004]})
    v.report()
    print(f"\nPhase 4 self-test: {'PASS' if v.passed else 'FAIL'}")
    return v.passed


if __name__ == "__main__":
    _self_test_phase1()
    _self_test_phase2()
    print("\nPhase 3 — strict mode (anti-cheat):")
    _self_test_phase3()
    print("\nPhase 4 — positive control (synthetic real edge):")
    _self_test_phase4()
