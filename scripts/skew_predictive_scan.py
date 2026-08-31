"""
skew_predictive_scan.py — does QQQ options skew predict forward NQ returns?

THE QUESTION. Igor's thesis: when skew steepens fast (urgent demand for downside puts),
market makers must sell futures to hedge -> downward pressure. The order-book leg (OBI) is
dead on arrival because it decays sub-second. Skew is the leg that carries real information:
per-day R^2 of skew against spot is 0.16, versus 0.70+ for tilt/net_gex, which are price
transforms wearing an options costume.

So before building anything, the cheap decisive test: sort skew moves into deciles and look
at what happens NEXT.

THE RULES THIS OBEYS (docs/LEAK_CHECKLIST.md):
  - The decision at bar i uses skew[i] and skew[i-k]. Both known at bar i. No peeking.
  - Forward return is measured from bar i+1's OPEN, never bar i's close. If you can't fill
    it, it isn't a return. This is the rule that turned a 1.74 PF into 1.02 on 2026-07-20.
  - t-stats are clustered BY DAY. 5-min bars inside a day are heavily autocorrelated;
    treating 39,000 overlapping observations as independent inflates t-stats ~5-10x and is
    the single most common way a scan like this manufactures significance.

This is a SCAN, not a backtest. It produces no PF and no edge claim. If something here looks
alive it goes through toolkit/harness.py audit() with a momentum-matched placebo before any
number gets believed.

Timezone: NQ bars are `m` = minutes since midnight CENTRAL. QQQ greeks are `hm` = "HH:MM" ET.
ET = CT + 60 minutes. Getting this wrong shifts the signal an hour and fakes an edge.

Run: python3 scripts/skew_predictive_scan.py
"""
import numpy as np
import pandas as pd

pd.options.mode.chained_assignment = None

NQ = "data/pkl/nq_5m_all.pkl"
GMAG = "data/pkl/gmag_path.pkl"

LAGS = [1, 3, 6]            # bars over which to measure the skew CHANGE (5, 15, 30 min)
HORIZONS = [1, 2, 6, 12]    # forward bars to hold (5, 10, 30, 60 min)
N_DECILES = 10


def load_merged():
    nq = pd.read_pickle(NQ)
    g = pd.read_pickle(GMAG)

    # NQ: minutes since midnight CENTRAL -> ET
    nq["et"] = nq["m"] + 60
    # gmag: "HH:MM" in ET -> minutes
    hm = g["hm"].str.split(":", expand=True).astype(int)
    g["et"] = hm[0] * 60 + hm[1]

    df = nq.merge(g[["date", "et", "skew", "spot"]],
                  left_on=["d", "et"], right_on=["date", "et"], how="inner")
    df = df.sort_values(["d", "et"]).reset_index(drop=True)
    print(f"merged: {len(df):,} bars, {df['d'].nunique()} days, "
          f"{df['d'].min()} -> {df['d'].max()}")
    return df


def add_features(df):
    gb = df.groupby("d", sort=False)
    for k in LAGS:
        # change in skew over the last k bars — known at bar i
        df[f"dskew{k}"] = gb["skew"].diff(k)
    for h in HORIZONS:
        # HONEST FILL: enter at bar i+1's open, exit h bars later at the open.
        # shift(-1) is the entry, shift(-(1+h)) is the exit.
        entry = gb["o"].shift(-1)
        exit_ = gb["o"].shift(-(1 + h))
        df[f"fwd{h}"] = exit_ / entry - 1.0
    return df


def day_clustered_t(daily_means):
    """t-stat across DAYS, not across bars. Bars within a day are not independent."""
    x = daily_means.dropna().values
    if len(x) < 5:
        return np.nan
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))


def decile_table(df, feat, horizon):
    sub = df[[feat, f"fwd{horizon}", "d"]].dropna()
    if len(sub) < 1000:
        return None
    # rank into deciles ACROSS the whole sample
    sub["dec"] = pd.qcut(sub[feat], N_DECILES, labels=False, duplicates="drop")

    rows = []
    for dec, gg in sub.groupby("dec"):
        # mean per day first, then aggregate -> honest error bars
        daily = gg.groupby("d")[f"fwd{horizon}"].mean()
        rows.append({
            "decile": int(dec) + 1,
            "n": len(gg),
            "mean_bps": gg[f"fwd{horizon}"].mean() * 1e4,
            "t": day_clustered_t(daily),
        })
    return pd.DataFrame(rows)


def main():
    df = add_features(load_merged())

    print(f"\nskew: mean {df['skew'].mean():.3f}  sd {df['skew'].std():.3f}")
    print("Thesis: skew STEEPENS (top decile of dskew) -> NQ falls. "
          "So we want decile 10 mean_bps NEGATIVE.\n")

    for k in LAGS:
        feat = f"dskew{k}"
        print("=" * 72)
        print(f"  feature: {feat}  (skew change over {k} bars = {k*5} min)")
        for h in HORIZONS:
            tab = decile_table(df, feat, h)
            if tab is None:
                continue
            lo, hi = tab.iloc[0], tab.iloc[-1]
            spread = hi["mean_bps"] - lo["mean_bps"]
            print(f"\n  forward {h} bars ({h*5} min), entry at next open:")
            print(f"    decile  1 (skew falls) : {lo['mean_bps']:+7.2f} bps  "
                  f"t={lo['t']:+5.2f}  n={lo['n']:,}")
            print(f"    decile 10 (skew rises) : {hi['mean_bps']:+7.2f} bps  "
                  f"t={hi['t']:+5.2f}  n={hi['n']:,}")
            print(f"    spread (10 - 1)        : {spread:+7.2f} bps")
            # monotonicity: does the effect grow across deciles, or is it one lucky bucket?
            rho = tab["decile"].corr(tab["mean_bps"], method="spearman")
            print(f"    monotonic across deciles (spearman): {rho:+.2f}")

    # ---- the level of skew, not just its change --------------------------
    print("\n" + "=" * 72)
    print("  feature: skew LEVEL (is high skew itself bearish?)")
    for h in HORIZONS:
        tab = decile_table(df, "skew", h)
        if tab is None:
            continue
        lo, hi = tab.iloc[0], tab.iloc[-1]
        print(f"    fwd {h:>2} bars: dec1 {lo['mean_bps']:+7.2f} (t={lo['t']:+5.2f})  "
              f"dec10 {hi['mean_bps']:+7.2f} (t={hi['t']:+5.2f})  "
              f"spread {hi['mean_bps']-lo['mean_bps']:+7.2f} bps")

    print("\n" + "=" * 72)
    print("  Reading this: |t| < 2 is noise. A real effect is monotonic across deciles,")
    print("  not one bucket. Spread of a few bps on 5-min NQ is not tradable after any")
    print("  realistic execution. This scan produces NO profit factor by design.")


if __name__ == "__main__":
    main()
