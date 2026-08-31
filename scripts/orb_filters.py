"""
Paper 2 Table 1 filters for the ORB, plus Paper 1's regime screens.

    Entry filter : ATR(20) of entry bar > 50th pct of 20-session ATR(20)
    Entry filter : Hurst > 0.50            (Paper 1 Filter 4, 60-90d daily returns)
    Best regime  : VIX 18-35               (Paper 1 Filter 2)
    Stand down   : H < 0.45, VIX < 13, ATR(20) below 50th pct

EVERY filter value below is read off a session STRICTLY BEFORE the one it gates.
That is the whole point -- a regime label built from the day it trades is hindsight,
and it is the single likeliest way this strategy could fake an edge.
"""
import numpy as np
import pandas as pd


def daily_frame(bars):
    """Collapse the 5-min sessions into daily OHLC. Index = day string, sorted."""
    rows = []
    for d, g in bars.items():
        rows.append((str(d), g["o"].iloc[0], g["h"].max(), g["l"].min(), g["c"].iloc[-1]))
    df = pd.DataFrame(rows, columns=["d", "o", "h", "l", "c"]).sort_values("d")
    return df.set_index("d")


def hurst_rs(x):
    """
    Classic rescaled-range Hurst. x = 1-D array of returns.
    H > 0.5 persistent/trending, H = 0.5 random walk, H < 0.5 mean-reverting.
    """
    x = np.asarray(x, float)
    n = len(x)
    sizes = [s for s in (8, 16, 32, 64) if s <= n // 2]
    if len(sizes) < 2:
        return np.nan
    logs, logn = [], []
    for s in sizes:
        rs = []
        for start in range(0, n - s + 1, s):
            w = x[start:start + s]
            sd = w.std(ddof=1)
            if sd <= 0:
                continue
            z = np.cumsum(w - w.mean())
            rs.append((z.max() - z.min()) / sd)
        if rs:
            logs.append(np.log(np.mean(rs)))
            logn.append(np.log(s))
    if len(logs) < 2:
        return np.nan
    return float(np.polyfit(logn, logs, 1)[0])


def regime_tables(bars, vix_path="data/pkl/vix_daily.pkl", hurst_win=90):
    """
    Returns a DataFrame indexed by day with the regime columns for THAT day,
    every one of them SHIFTED so it uses only sessions strictly before it.
    """
    df = daily_frame(bars)

    # --- daily true range -> ATR(20) -------------------------------------
    pc = df["c"].shift(1)
    tr = pd.concat([df["h"] - df["l"], (df["h"] - pc).abs(), (df["l"] - pc).abs()],
                   axis=1).max(axis=1)
    atr20 = tr.rolling(20).mean()

    # ATR(20) vs its own median over the last 20 sessions.
    # .shift(1) FIRST: today's ATR must not include today's range.
    atr20_prior = atr20.shift(1)
    atr20_med   = atr20_prior.rolling(20).median()
    out = pd.DataFrame(index=df.index)
    out["atr20"]      = atr20_prior
    out["atr20_med"]  = atr20_med
    out["atr20_high"] = atr20_prior > atr20_med          # Table 1 entry filter

    # --- Hurst on trailing daily returns ---------------------------------
    ret = np.log(df["c"]).diff()
    h = ret.rolling(hurst_win).apply(hurst_rs, raw=True)
    out["hurst"] = h.shift(1)                            # strictly prior sessions

    # --- VIX (prior session's close) -------------------------------------
    try:
        vix = pd.read_pickle(vix_path)
        out["vix"] = vix["vix_close"].reindex(out.index).shift(1)
    except FileNotFoundError:
        out["vix"] = np.nan
    return out


def make_filtered_signal(base_signal, reg, *, need_hurst=None, need_atr=False,
                         vix_lo=None, vix_hi=None):
    """Wrap a signal so it only fires when the PRIOR-session regime allows it."""
    def sig(day, g):
        t = base_signal(day, g)
        if not t:
            return []
        r = reg.loc[str(day)] if str(day) in reg.index else None
        if r is None:
            return []
        if need_atr and not bool(r["atr20_high"]):
            return []
        if need_hurst is not None:
            if not np.isfinite(r["hurst"]) or r["hurst"] <= need_hurst:
                return []
        if vix_lo is not None:
            if not np.isfinite(r["vix"]) or not (vix_lo <= r["vix"] <= vix_hi):
                return []
        return t
    return sig
