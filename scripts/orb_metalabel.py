"""
orb_metalabel.py — can a model tell WHICH opening-range breakouts to take?

THE SETUP. The raw ORB is not tradable: PF 1.13 on MGC but 1.08 on independently-sourced GC
with a bootstrap 5th percentile below 1.0, i.e. the "edge" was partly a sample-window
artifact. What DID replicate, across three series and two markets, is the volatility split:

    low-vol / high-vol PF     MGC 0.39/1.94    GC 0.38/1.84    SI 0.46/1.95

That is a real conditional effect, and it is the precondition for ML meaning anything here.
We are NOT asking a model to predict gold. We are asking: given a breakout just triggered,
and given vol regime + dealer positioning, is THIS one worth taking? That is meta-labeling —
the model filters a mechanical signal it did not invent.

*** THE FOUR WAYS THIS COULD LIE, AND WHAT STOPS EACH ***

1. FEATURE LOOKAHEAD. Every feature must be knowable before the entry bar. Entry is bar i+1's
   open, so features may use bars 0..i of today plus STRICTLY PRIOR days. ATR and trailing
   returns are shifted by one day. Asserted at build time, not assumed.

2. OPTIONS LOOKAHEAD. 7.3% of GLD chain files are stamped after their own day's close. Joined
   with merge_asof(..., allow_exact_matches=False) so trading day T only ever sees a snapshot
   STRICTLY BEFORE T. See build_gld_option_features.py.

3. CV LEAKAGE. Standard k-fold would train on the future and test on the past. This uses
   expanding-window walk-forward with an EMBARGO gap between train and test.

4. THE MODEL FINDING NOISE. A flexible model on ~1500 rows will always find something. The
   permutation test re-runs the whole pipeline with SHUFFLED labels many times to build the
   null distribution. If the real result sits inside that distribution, there is nothing here.

Model choice is deliberately varied (gradient boosting / random forest / extra trees /
logistic) to demonstrate the point that it is the least important variable — honest CV
matters far more than which learner you pick.

Nothing here reports a PF. The winner, if any, goes through toolkit/harness.py audit().

Run: python3 scripts/orb_metalabel.py
"""
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import (ExtraTreesClassifier, HistGradientBoostingClassifier,
                              RandomForestClassifier)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, "toolkit")
sys.path.insert(0, "scripts")
from gold_orb_audit import orb_signal          # noqa: E402
from harness import PF, backtest, load_bars    # noqa: E402

warnings.filterwarnings("ignore")

N_BARS = 6              # opening range = first 6 bars (30 min)
STOP, TARGET = 0.003, 0.006
EMBARGO_DAYS = 5
N_SPLITS = 6
N_PERM = 200
SEED = 20260720


# ----------------------------------------------------------------- features
def daily_context(bars):
    """Per-day features built ONLY from strictly prior days.

    `bars` is {day: DataFrame} as returned by harness.load_bars.

    The .shift(1) below is the whole ballgame: without it, today's range is in today's
    ATR and the model gets to see how volatile today turned out to be.
    """
    d = pd.DataFrame(
        {day: {"o": g["o"].iloc[0], "h": g["h"].max(),
               "l": g["l"].min(), "c": g["c"].iloc[-1]}
         for day, g in bars.items()}
    ).T.sort_index()
    tr = (d["h"] - d["l"]) / d["c"]
    ctx = pd.DataFrame(index=d.index)
    ctx["atr5"] = tr.rolling(5).mean().shift(1)      # shift(1) => prior days only
    ctx["atr20"] = tr.rolling(20).mean().shift(1)
    ctx["atr_ratio"] = ctx["atr5"] / ctx["atr20"]
    ret = d["c"].pct_change()
    ctx["rvol20"] = ret.rolling(20).std().shift(1)
    ctx["ret5"] = d["c"].pct_change(5).shift(1)
    ctx["ret20"] = d["c"].pct_change(20).shift(1)
    ctx["prev_close"] = d["c"].shift(1)
    ctx["dow"] = pd.to_datetime(d.index).dayofweek
    return ctx


def build_trades(name, tick):
    """Run the raw ORB, then attach causal features to every trigger."""
    bars = load_bars(f"data/pkl/{name}_5m.pkl", min_bars=60)
    trades = backtest(orb_signal(N_BARS, fade=False), bars,
                      stop=STOP, target=TARGET, one_per_day=True, tick=tick)
    ctx = daily_context(bars)

    by_day = bars          # load_bars already returns {day: frame} indexed 0..n-1
    rows = []
    for t in trades:
        g = by_day[t.day]
        i = t.i
        head = g.iloc[:N_BARS]
        orh, orl = head["h"].max(), head["l"].min()
        c_i = g["c"].iloc[i]
        cx = ctx.loc[t.day]
        if not np.isfinite(cx["atr20"]) or cx["atr20"] <= 0:
            continue
        rows.append({
            "inst": name, "day": t.day, "i": i, "direction": t.direction,
            "ret": t.ret, "win": int(t.ret > 0),
            # --- shape of today's setup, all from bars 0..i ---------------
            "or_width": (orh - orl) / c_i,
            "or_width_atr": ((orh - orl) / c_i) / cx["atr20"],
            "trigger_bar": i,
            "gap": g["o"].iloc[0] / cx["prev_close"] - 1,
            "dist_from_or": (c_i - orh) / c_i if t.direction > 0 else (orl - c_i) / c_i,
            # --- regime, strictly prior days ------------------------------
            "atr20": cx["atr20"], "atr_ratio": cx["atr_ratio"],
            "rvol20": cx["rvol20"], "ret5": cx["ret5"], "ret20": cx["ret20"],
            "dow": cx["dow"],
        })
    df = pd.DataFrame(rows)
    df["day"] = pd.to_datetime(df["day"])
    return df.sort_values("day").reset_index(drop=True)


def attach_options(df):
    """Join GLD features using ONLY snapshots strictly before the trading day."""
    opt = pd.read_pickle("data/pkl/gld_opt_daily.pkl").sort_index().reset_index()
    opt = opt.rename(columns={"snapshot_date": "day"})
    merged = pd.merge_asof(
        df.sort_values("day"), opt.sort_values("day"),
        on="day", direction="backward",
        allow_exact_matches=False,      # <- strictly BEFORE. the whole causality guarantee.
        tolerance=pd.Timedelta("7D"),
    )
    return merged


# ----------------------------------------------------------------- CV
def walk_forward(df, feats, model_fn, seed=SEED, shuffle_y=False):
    """Expanding-window walk-forward with an embargo. Returns OOS predictions.

    Test folds are contiguous blocks of TIME. Training uses everything up to the fold
    start minus EMBARGO_DAYS. Nothing from the future ever reaches a training set.
    """
    df = df.sort_values("day").reset_index(drop=True)
    X, y = df[feats].values, df["win"].values
    if shuffle_y:
        y = np.random.default_rng(seed).permutation(y)

    n = len(df)
    edges = np.linspace(n // 3, n, N_SPLITS + 1).astype(int)   # first 1/3 is train-only
    oof = np.full(n, np.nan)

    for k in range(N_SPLITS):
        te0, te1 = edges[k], edges[k + 1]
        if te1 <= te0:
            continue
        cutoff = df["day"].iloc[te0] - pd.Timedelta(days=EMBARGO_DAYS)
        tr = df.index[(df["day"] < cutoff) & (df.index < te0)].values
        if len(tr) < 150 or len(np.unique(y[tr])) < 2:
            continue
        m = model_fn(seed)
        m.fit(X[tr], y[tr])
        oof[te0:te1] = m.predict_proba(X[te0:te1])[:, 1]
    return oof


MODELS = {
    "hist_gbm": lambda s: HistGradientBoostingClassifier(
        max_depth=3, max_iter=150, learning_rate=0.05, random_state=s),
    "random_forest": lambda s: RandomForestClassifier(
        n_estimators=300, min_samples_leaf=25, random_state=s, n_jobs=-1),
    "extra_trees": lambda s: ExtraTreesClassifier(
        n_estimators=300, min_samples_leaf=25, random_state=s, n_jobs=-1),
    "logistic": lambda s: make_pipeline(
        StandardScaler(), LogisticRegression(C=0.1, max_iter=2000, random_state=s)),
}


def evaluate(df, oof):
    """Economics of acting on the model, versus taking every trade."""
    m = np.isfinite(oof)
    sub, p = df[m], oof[m]
    if len(sub) < 50:
        return None
    base_pf = PF(sub["ret"].values)
    thr = np.median(p)                 # take the better half. threshold is NOT tuned on test.
    sel = sub[p >= thr]
    return {
        "n_oos": len(sub),
        "auc": roc_auc_score(sub["win"], p) if sub["win"].nunique() > 1 else np.nan,
        "base_pf": base_pf,
        "sel_pf": PF(sel["ret"].values) if len(sel) > 20 else np.nan,
        "n_sel": len(sel),
    }


def run(df, feats, label):
    # drop rows with missing features (the first 20 days have no ATR20 yet, etc.).
    # Done here rather than imputing: a fabricated feature value is a quiet lie.
    df = df.dropna(subset=feats).reset_index(drop=True)
    print("\n" + "=" * 74)
    print(f"  {label}   n={len(df)}  features={len(feats)}")
    print("=" * 74)
    print(f"  {'model':<15}{'OOS AUC':>9}{'PF all':>9}{'PF selected':>13}{'n sel':>8}")

    results = {}
    for nm, fn in MODELS.items():
        r = evaluate(df, walk_forward(df, feats, fn))
        if r:
            results[nm] = r
            print(f"  {nm:<15}{r['auc']:>9.3f}{r['base_pf']:>9.3f}"
                  f"{r['sel_pf']:>13.3f}{r['n_sel']:>8}")

    if not results:
        return
    best = max(results, key=lambda k: results[k]["sel_pf"])
    real = results[best]["sel_pf"]

    # ---- permutation test: is `real` distinguishable from shuffled labels? ----
    print(f"\n  permutation test on '{best}' ({N_PERM} shuffles of the labels)...")
    null = []
    for j in range(N_PERM):
        oof = walk_forward(df, feats, MODELS[best], seed=SEED + j, shuffle_y=True)
        r = evaluate(df, oof)
        if r and np.isfinite(r["sel_pf"]):
            null.append(r["sel_pf"])
    null = np.array(null)
    pval = (null >= real).mean()
    print(f"    real selected PF : {real:.3f}")
    print(f"    shuffled null    : median {np.median(null):.3f}  "
          f"p90 {np.percentile(null,90):.3f}  p99 {np.percentile(null,99):.3f}")
    print(f"    p-value          : {pval:.3f}   "
          f"{'<- nothing here' if pval > 0.05 else '<- worth a real audit'}")


if __name__ == "__main__":
    PRICE_FEATS = ["or_width", "or_width_atr", "trigger_bar", "gap", "dist_from_or",
                   "atr20", "atr_ratio", "rvol20", "ret5", "ret20", "dow", "direction"]

    frames = [build_trades("gc", 0.10), build_trades("si", 0.005)]
    for f in frames:
        print(f"{f['inst'].iloc[0]}: {len(f)} trades, "
              f"{f['day'].min().date()} -> {f['day'].max().date()}, "
              f"win rate {f['win'].mean():.3f}")

    gc = frames[0]
    run(gc, PRICE_FEATS, "GC — price/vol features only (full sample)")

    gco = attach_options(gc).dropna(subset=["atm_iv"])
    OPT_FEATS = [c for c in gco.columns if c.startswith(("atm_", "skew", "pc_", "gamma_",
                                                         "term_", "d1_", "d5_", "z60_"))]
    run(gco, PRICE_FEATS + OPT_FEATS, "GC — price/vol + GLD options (chain overlap only)")

    # silver: same machinery, and it must hold here too or it's instrument-specific noise
    run(frames[1], PRICE_FEATS, "SI — price/vol features only (replication check)")
