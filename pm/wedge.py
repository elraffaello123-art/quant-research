"""
wedge.py — estimate the Wang-transform pricing wedge on Kalshi, twice.

    p_mkt = Phi( Phi^-1(p*) + lambda )

Yang (2026) fits this to 291,309 resolved contracts and reports lambda_CI =
0.178 on Kalshi, i.e. prices sitting systematically above physical
probabilities. His estimate uses hourly MID prices.

A mid is not a price you can trade. This module estimates lambda three ways on
the same contracts:

  mid   - replicate the paper: (yes_bid + yes_ask) / 2
  exec  - the price a taker could actually have hit, on the side the wedge
          says to trade: you SELL the overpriced side, so you hit the BID
  net   - exec, minus Kalshi's trading fee

If the wedge is a tradeable mispricing, it survives `net`. If it is a risk
premium paid to makers for bearing inventory and adverse-selection risk, it
lives entirely inside the spread and dies between `mid` and `exec`. That is
the whole question, and the two hypotheses make opposite predictions about
the same number.

Usage:
    python3 wedge.py            # full run, prints every table
"""

import json
import math
import os
import glob

import numpy as np
from scipy.stats import norm
from scipy.optimize import minimize_scalar

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CANDLES = os.path.join(DATA, "candles")

EPS = 1e-6
# Paper's boundary filter: logit blows up noise outside this band.
P_LO, P_HI = 0.02, 0.98
# Paper's "opening price" = first 5% of the contract's lifetime.
OPEN_TAU = 0.05


# ------------------------------------------------------------------ helpers
def _f(d, key):
    """Kalshi returns money as decimal strings; missing legs as {}."""
    v = d.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _iso_ts(s):
    import datetime
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def kalshi_fee(price, contracts=1, multiplier=1.0):
    """Kalshi trading fee: 0.07 * C * p * (1-p), rounded up to the cent.

    Charged to takers. Quoted per contract here, in dollars.
    """
    raw = 0.07 * contracts * price * (1.0 - price) * multiplier
    return math.ceil(raw * 100) / 100.0


# ------------------------------------------------------------------- loader
def load_panel(max_markets=None):
    """Join settled markets to their candlestick paths.

    Returns a list of dicts, one per contract, holding the opening quote
    (bid/ask/mid) and the resolution outcome.
    """
    mpath = os.path.join(DATA, "markets_raw.jsonl")
    markets = {}
    for line in open(mpath):
        m = json.loads(line)
        markets[m["ticker"]] = m

    rows = []
    files = glob.glob(os.path.join(CANDLES, "*.json"))
    if max_markets:
        files = files[:max_markets]

    for fp in files:
        try:
            c = json.load(open(fp))
        except Exception:
            continue
        m = markets.get(c["ticker"])
        if not m:
            continue
        cs = c.get("candlesticks") or []
        if len(cs) < 4:                       # paper: >= 4 observations
            continue
        try:
            t0, t1 = _iso_ts(m["open_time"]), _iso_ts(m["close_time"])
        except Exception:
            continue
        if t1 <= t0:
            continue

        # Build the quote path, keeping only periods with a two-sided book.
        path = []
        for k in cs:
            ts = k.get("end_period_ts")
            bid = _f(k.get("yes_bid") or {}, "close_dollars")
            ask = _f(k.get("yes_ask") or {}, "close_dollars")
            if ts is None or bid is None or ask is None:
                continue
            if ask <= bid:                    # crossed/locked: not a real book
                continue
            if bid <= 0.0 and ask >= 1.0:     # empty book quoted 0/1
                continue
            path.append((ts, bid, ask))
        if len(path) < 4:
            continue

        # The paper's opening price: first observation at or past 5% of life.
        cutoff = t0 + OPEN_TAU * (t1 - t0)
        pick = next((p for p in path if p[0] >= cutoff), path[0])
        ts, bid, ask = pick
        mid = 0.5 * (bid + ask)
        if not (P_LO < mid < P_HI):
            continue

        try:
            vol = float(m.get("volume_fp") or 0)
        except (TypeError, ValueError):
            vol = 0.0

        rows.append({
            "ticker": c["ticker"],
            "series": m.get("_series"),
            "category": m.get("_category") or "Unknown",
            "fee_mult": float(m.get("_fee_multiplier") or 1.0),
            "y": 1 if m["result"] == "yes" else 0,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": ask - bid,
            "volume": vol,
            "duration_h": (t1 - t0) / 3600.0,
            "n_obs": len(path),
        })
    return rows


# --------------------------------------------------------------------- MLE
def wang_mle(p, y):
    """lambda by maximum likelihood under Pr(y=1 | p) = Phi(Phi^-1(p) - lambda).

    Returns (lambda_hat, se, n). SE from the observed Fisher information,
    computed by numerical second difference of the log-likelihood.
    """
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    z = norm.ppf(p)

    def nll(lam):
        q = np.clip(norm.cdf(z - lam), EPS, 1 - EPS)
        return -np.sum(y * np.log(q) + (1 - y) * np.log(1 - q))

    r = minimize_scalar(nll, bounds=(-3.0, 3.0), method="bounded")
    lam = float(r.x)
    h = 1e-4
    d2 = (nll(lam + h) - 2 * nll(lam) + nll(lam - h)) / (h * h)
    se = float(1.0 / math.sqrt(d2)) if d2 > 0 else float("nan")
    return lam, se, len(p)


def complement_invariant(p, y):
    """Fold each contract onto its longshot side.

    The Wang transform is not framing-invariant: relabelling YES as NO sends
    lambda to -lambda. Exchanges enforce YES+NO=1, so the YES label carries no
    payoff content and a directional estimate can pick up pure labelling
    asymmetry. Folding to q = min(p, 1-p) isolates the part of the wedge that
    is a probability-LEVEL phenomenon (are longshots overpriced?) rather than a
    labelling artifact. This is the check that collapsed the paper's own
    Polymarket estimate from 0.165 to 0.049.
    """
    p = np.asarray(p, float)
    y = np.asarray(y, float)
    q = np.minimum(p, 1 - p)
    z = np.where(p <= 0.5, y, 1 - y)
    keep = (q > P_LO) & (q < P_HI)
    return q[keep], z[keep]


def executable_fold(bid, ask, y):
    """Complement-invariant fold, but at the price you could actually RECEIVE.

    Careful here — this is easy to get wrong and I did get it wrong first time.
    The fold picks the longshot side and the strategy sells it. Selling means
    receiving that side's BID:

      longshot is YES (mid <= 0.5)  ->  you receive the YES bid  = bid
      longshot is NO  (mid  > 0.5)  ->  you receive the NO  bid  = 1 - ASK

    Folding the YES bid as `min(bid, 1-bid)` would use `1 - yes_bid` for the NO
    half, which is the NO *ask* — the price you'd PAY to buy NO, not the price
    you'd receive for selling it. That flatters the estimate by a full spread on
    half the sample, and on this data the median spread is ~9c.
    """
    bid = np.asarray(bid, float)
    ask = np.asarray(ask, float)
    y = np.asarray(y, float)
    mid = 0.5 * (bid + ask)
    q = np.where(mid <= 0.5, bid, 1.0 - ask)
    z = np.where(mid <= 0.5, y, 1 - y)
    keep = (q > P_LO) & (q < P_HI)
    return q[keep], z[keep]


def fmt(lam, se, n, label):
    t = lam / se if se and not math.isnan(se) else float("nan")
    stars = "***" if abs(t) > 3.29 else "**" if abs(t) > 2.58 else "*" if abs(t) > 1.96 else ""
    return f"  {label:<34s} lambda={lam:+.4f}  SE={se:.4f}  t={t:+6.2f}{stars:<3s}  N={n:,}"


# ---------------------------------------------------------- economic layer
def edge_cents(lam, q):
    """Gross edge in cents from selling a contract quoted at q when the
    complement-invariant wedge is lam: q - Phi(Phi^-1(q) - lam)."""
    fair = norm.cdf(norm.ppf(q) - lam)
    return 100.0 * (q - fair)


def main():
    rows = load_panel()
    if not rows:
        print("no rows — run kalshi_fetch.py first")
        return
    print(f"\ncontracts with a usable opening book: {len(rows):,}")

    mid = np.array([r["mid"] for r in rows])
    bid = np.array([r["bid"] for r in rows])
    ask = np.array([r["ask"] for r in rows])
    y = np.array([r["y"] for r in rows])
    spread = np.array([r["spread"] for r in rows])

    print(f"median spread: {np.median(spread)*100:.2f}c   "
          f"mean: {spread.mean()*100:.2f}c   "
          f"p90: {np.percentile(spread,90)*100:.2f}c")

    print("\n" + "=" * 78)
    print("1. DIRECTIONAL lambda (replicating the paper's specification)")
    print("=" * 78)
    print(fmt(*wang_mle(mid, y), "mid  (paper's estimator)"))

    print("\n" + "=" * 78)
    print("2. COMPLEMENT-INVARIANT lambda — is it a level effect or a label artifact?")
    print("=" * 78)
    q_m, z_m = complement_invariant(mid, y)
    print(fmt(*wang_mle(q_m, z_m), "mid"))

    print("\n" + "=" * 78)
    print("3. THE HONEST-PRICE TEST — can a taker actually get this?")
    print("=" * 78)
    print("   The wedge says the quoted side is overpriced, so you SELL it.")
    print("   Selling means hitting the BID, not the mid. Fees come off after.\n")

    q_e, z_e = executable_fold(bid, ask, y)
    print(fmt(*wang_mle(q_e, z_e), "exec (receive the longshot's bid)"))

    lam_mid = wang_mle(q_m, z_m)[0]
    lam_exe = wang_mle(q_e, z_e)[0]

    # A wide book is not a book. The wedge is largest exactly where spreads are
    # widest, so a spread filter is not a neutral robustness cut — it is the
    # trade-off itself. Report it stratified rather than picking one threshold.
    print("\n  by spread (the mid estimate assumes you capture half of this free):")
    for lab, lo, hi in (("tight  <=2c ", -1, 0.02),
                        ("mid   2-10c ", 0.02, 0.10),
                        ("wide   >10c ", 0.10, 9.0)):
        msk = (spread > lo) & (spread <= hi)
        if msk.sum() < 50:
            continue
        qq, zz = complement_invariant(mid[msk], y[msk])
        qe, ze = executable_fold(bid[msk], ask[msk], y[msk])
        lm = wang_mle(qq, zz)
        le = wang_mle(qe, ze)
        print(fmt(*lm, f"{lab} mid "))
        print(fmt(*le, f"{lab} exec"))

    print("\n" + "=" * 78)
    print("4. WHAT IT IS WORTH, IN CENTS")
    print("=" * 78)
    print(f"   {'quoted':>8s} {'edge@mid':>10s} {'edge@exec':>11s} {'fee':>7s} {'net':>8s}")
    for q in (0.05, 0.10, 0.20, 0.35, 0.50):
        em = edge_cents(lam_mid, q)
        ee = edge_cents(lam_exe, q)
        fee = kalshi_fee(q) * 100.0
        print(f"   {q:8.2f} {em:9.2f}c {ee:10.2f}c {fee:6.2f}c {ee-fee:7.2f}c")

    print("\n   Median spread is "
          f"{np.median(spread)*100:.2f}c. Half of that is what the mid estimate")
    print("   silently assumes you capture for free.")

    # ------------------------------------------------ cross-section
    print("\n" + "=" * 78)
    print("5. CROSS-SECTION — does the paper's economics replicate?")
    print("=" * 78)
    vol = np.array([r["volume"] for r in rows])
    dur = np.array([r["duration_h"] for r in rows])

    for name, arr in (("volume", vol), ("duration (h)", dur)):
        qs = np.percentile(arr, [33, 67])
        print(f"\n  by {name}:")
        for lab, msk in (("low   ", arr <= qs[0]),
                         ("mid   ", (arr > qs[0]) & (arr <= qs[1])),
                         ("high  ", arr > qs[1])):
            if msk.sum() < 50:
                continue
            qq, zz = complement_invariant(mid[msk], y[msk])
            l, s, n = wang_mle(qq, zz)
            sp = np.median(spread[msk]) * 100
            print(fmt(l, s, n, f"{lab} (median spread {sp:5.2f}c)"))

    print("\n  by category:")
    cats = {}
    for i, r in enumerate(rows):
        cats.setdefault(r["category"], []).append(i)
    for c, idx in sorted(cats.items(), key=lambda kv: -len(kv[1]))[:10]:
        if len(idx) < 100:
            continue
        idx = np.array(idx)
        qq, zz = complement_invariant(mid[idx], y[idx])
        if len(qq) < 100:
            continue
        l, s, n = wang_mle(qq, zz)
        sp = np.median(spread[idx]) * 100
        print(fmt(l, s, n, f"{c[:22]:<22s} (spr {sp:5.2f}c)"))


if __name__ == "__main__":
    main()
