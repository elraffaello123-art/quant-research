"""
vrp.py — is there a harvestable variance risk premium in Kalshi's 15-minute
crypto binaries?

Lee, Lee & Lee (2026) report implied variance above realised variance across all
series. That is a claim about a *hedged* position: a VRP is harvested by selling
the option and delta-hedging the underlying, which needs no directional view.
Everything measured in wedge.py and favourites.py was an UNHEDGED binary held to
settlement, so it is a different trade and those results do not speak to this one.

This module:

  1. Inverts the cash-or-nothing digital formula for implied vol at contract open.
       price = N(d2),  d2 = [ln(S/K) - 0.5*sigma^2*tau] / (sigma*sqrt(tau))
     Everything is in per-second vol units with tau in seconds, so no annualisation
     convention can quietly enter the comparison.

  2. Measures realised vol from Binance 1-second closes over the same window.

  3. Simulates the actual trade: sell the binary at the BID, delta-hedge on spot
     at a chosen frequency, pay Kalshi's fee and Binance's taker fee, settle.

The known hazard is specific and is the reason to simulate rather than reason:
a digital's delta is n(d2)/(S*sigma*sqrt(tau)), which diverges as tau -> 0 with S
near K. The hedge is most violent exactly when it matters most.
"""

import glob
import json
import math
import os

import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq

import wedge as W
from binance_fetch import SERIES_TO_SYMBOL

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# Binance spot taker fee. 0.10% is the standard tier; 0.075% paying fees in BNB.
# Use the standard tier — assuming the discount is assuming a decision you may
# not want to make.
SPOT_FEE = 0.0010


# ------------------------------------------------------------------- loading
def load_spot():
    """symbol -> (unix_seconds array, close array). 1s klines, microsecond ts."""
    out = {}
    for fp in sorted(glob.glob(os.path.join(DATA, "binance", "*-1s-*.csv"))):
        sym = os.path.basename(fp).split("-")[0]
        a = np.loadtxt(fp, delimiter=",", usecols=(0, 4))
        ts = (a[:, 0] / 1e6).astype(np.int64)
        out.setdefault(sym, []).append((ts, a[:, 1]))
    joined = {}
    for sym, parts in out.items():
        parts.sort(key=lambda p: p[0][0])
        joined[sym] = (np.concatenate([p[0] for p in parts]),
                       np.concatenate([p[1] for p in parts]))
    return joined


def price_at(ts_arr, px_arr, t):
    """Last trade price at or before t. Returns None if outside coverage."""
    i = np.searchsorted(ts_arr, t, side="right") - 1
    if i < 0 or i >= len(px_arr):
        return None
    if t - ts_arr[i] > 120:          # a two-minute stale quote is not a price
        return None
    return float(px_arr[i])


# ------------------------------------------------------------ digital option
def digital_price(S, K, sigma, tau):
    if sigma <= 0 or tau <= 0:
        return 1.0 if S >= K else 0.0
    d2 = (math.log(S / K) - 0.5 * sigma * sigma * tau) / (sigma * math.sqrt(tau))
    return float(norm.cdf(d2))


def implied_vol(price, S, K, tau):
    """Invert the digital for per-second sigma. None if the price is unreachable.

    The digital is NOT monotone in sigma out of the money, and getting this
    wrong silently destroys the sample. With x = ln(S/K) and u = sigma*sqrt(tau),

        d2 = x/u - u/2

    For x < 0 (out of the money) d2 -> -inf at both u -> 0 and u -> inf, so the
    price rises from 0, peaks, and falls back. The peak is at u* = sqrt(2|x|),
    where the price is N(-sqrt(2|x|)) — for a 15-minute crypto contract with S
    within a few bp of K that ceiling is just under 0.50.

    Bracketing on [tiny, huge] therefore has f < 0 at BOTH ends for any OTM
    quote priced under the ceiling, brentq sees no sign change, and the contract
    is dropped. That bug threw away 52% of this sample, 98.5% of it OTM, leaving
    a panel selected almost entirely on being in the money.

    The economically meaningful root is the LOW-vol branch (more vol = more
    chance of reaching the strike), so bracket OTM on [tiny, u*].
    For x > 0 the price falls monotonically from 1, so a wide bracket is fine.
    """
    if not (0.001 < price < 0.999) or tau <= 0 or S <= 0:
        return None
    x = math.log(S / K)
    rt = math.sqrt(tau)
    f = lambda s: digital_price(S, K, s, tau) - price

    if x < 0:
        u_star = math.sqrt(2.0 * abs(x))
        ceiling = float(norm.cdf(-u_star))
        if price >= ceiling:
            return None                      # genuinely unreachable, not a bug
        hi = u_star / rt
    else:
        hi = 0.05

    lo = 1e-12
    try:
        if f(lo) * f(hi) > 0:
            return None
        return float(brentq(f, lo, hi, maxiter=200))
    except Exception:
        return None


def digital_delta(S, K, sigma, tau):
    if sigma <= 0 or tau <= 0:
        return 0.0
    srt = sigma * math.sqrt(tau)
    d2 = (math.log(S / K) - 0.5 * sigma * sigma * tau) / srt
    return float(norm.pdf(d2) / (S * srt))


# ---------------------------------------------------------------- the panel
def build(spot, obs_frac=0.05):
    markets = [json.loads(l) for l in open(os.path.join(DATA, "markets_randomness.jsonl"))]
    rows = []
    for m in markets:
        sym = SERIES_TO_SYMBOL.get(m.get("_series"))
        if not sym or sym not in spot:
            continue
        K = m.get("floor_strike")
        if not K or m.get("strike_type") not in ("greater_or_equal", "greater"):
            continue
        fp = os.path.join(DATA, "candles", m["ticker"].replace("/", "_") + ".json")
        if not os.path.exists(fp):
            continue
        try:
            c = json.load(open(fp))
            t0, t1 = W._iso_ts(m["open_time"]), W._iso_ts(m["close_time"])
        except Exception:
            continue
        if t1 <= t0:
            continue
        path = []
        for k in (c.get("candlesticks") or []):
            ts = k.get("end_period_ts")
            b = W._f(k.get("yes_bid") or {}, "close_dollars")
            a = W._f(k.get("yes_ask") or {}, "close_dollars")
            if ts is None or b is None or a is None or a <= b or b <= 0 or a >= 1:
                continue
            path.append((ts, b, a))
        if len(path) < 3:
            continue
        cutoff = t0 + obs_frac * (t1 - t0)
        ts, bid, ask = next((p for p in path if p[0] >= cutoff), path[0])
        if ts >= t1:
            continue

        tsa, pxa = spot[sym]
        S = price_at(tsa, pxa, ts)
        if S is None:
            continue
        tau = float(t1 - ts)
        mid = 0.5 * (bid + ask)
        iv = implied_vol(mid, S, K, tau)
        if iv is None:
            continue

        # realised vol over the remaining life, per second, from 1s closes
        i0 = np.searchsorted(tsa, ts, side="left")
        i1 = np.searchsorted(tsa, t1, side="right")
        seg = pxa[i0:i1]
        if len(seg) < 120:
            continue
        # Sample at several steps. 1-second Binance klines contain bars with no
        # trade, whose close repeats the previous close and contributes a zero
        # return; that biases 1s RV DOWN (measured: 1s RV is 0.78-0.99x the 60s
        # estimate across these symbols), which would bias IV/RV UP.
        rvs = {}
        for step in (1, 5, 15):
            sub = seg[::step]
            if len(sub) < 20:
                continue
            rr = np.diff(np.log(sub))
            v = float(rr.std(ddof=1)) / math.sqrt(step)
            if np.isfinite(v) and v > 0:
                rvs[step] = v
        if 1 not in rvs or 15 not in rvs:
            continue
        rv = rvs[1]

        rows.append({"ticker": m["ticker"], "sym": sym, "S": S, "K": K,
                     "bid": bid, "ask": ask, "mid": mid, "tau": tau,
                     "iv": iv, "rv": rv, "rv5": rvs.get(5), "rv15": rvs.get(15),
                     "ts": ts, "t1": t1,
                     "y": 1 if m["result"] == "yes" else 0,
                     "moneyness": math.log(S / K) / (rv * math.sqrt(tau))})
    return rows


# ------------------------------------------------------------ hedged trade
def simulate(rows, spot, hedge_secs=30, use_bid=True, spot_fee=SPOT_FEE):
    """Sell one binary, delta-hedge on spot, settle. P&L in dollars per contract.

    Short a $1 digital: our liability is V(S,t) = N(d2). Delta-neutral means
    holding pos = dV/dS units of spot. The whole question is the SIZE of that
    hedge: dV/dS = n(d2)/(S*sigma*sqrt(tau)), so the notional held is
    n(d2)/(sigma*sqrt(tau)) DOLLARS per $1 of binary. With sigma*sqrt(tau) ~ 0.003
    near the money that is ~$130 of spot to hedge a $1 contract, and every
    rebalance pays taker fee on the traded notional.
    """
    out = []
    for r in rows:
        tsa, pxa = spot[r["sym"]]
        entry = r["bid"] if use_bid else r["mid"]
        cash = entry - W.kalshi_fee(entry)
        sigma = r["iv"]
        pos = 0.0
        fees = 0.0
        turnover = 0.0
        t, S = r["ts"], r["S"]
        while True:
            tau = r["t1"] - t
            if tau <= 1:
                break
            tgt = digital_delta(S, r["K"], sigma, tau)
            trade = tgt - pos
            if abs(trade) * S > 0.005:
                notional = abs(trade) * S
                fees += notional * spot_fee
                turnover += notional
                cash -= trade * S
                pos = tgt
            t += hedge_secs
            nxt = price_at(tsa, pxa, min(t, r["t1"]))
            if nxt is None:
                break
            S = nxt
        cash += pos * S                       # unwind
        fees += abs(pos) * S * spot_fee
        turnover += abs(pos) * S
        payoff = 1.0 if r["y"] == 1 else 0.0
        out.append({"pnl": cash - payoff - fees, "gross": cash - payoff,
                    "fees": fees, "turnover": turnover, "sym": r["sym"],
                    "iv": r["iv"], "rv15": r.get("rv15")})
    return out


def main():
    print("loading Binance 1s klines ...", flush=True)
    spot = load_spot()
    print("  symbols:", {k: len(v[0]) for k, v in spot.items()})
    rows = build(spot)
    print(f"\ncontracts with strike, quote, spot and a solvable IV: {len(rows):,}")
    if not rows:
        return

    iv = np.array([r["iv"] for r in rows])
    rv = np.array([r["rv"] for r in rows])
    print("\n=== IS IMPLIED VOL ABOVE REALISED? (per-second vol) ===")
    print(f"  median IV {np.median(iv)*1e4:.2f} bp/s   median RV {np.median(rv)*1e4:.2f} bp/s")
    ratio = iv / rv
    print(f"  median IV/RV ratio: {np.median(ratio):.3f}")
    print(f"  share with IV > RV: {(iv>rv).mean()*100:.1f}%")
    d = iv - rv
    se = d.std(ddof=1) / math.sqrt(len(d))
    print(f"  mean IV-RV = {d.mean()*1e4:+.3f} bp/s   SE {se*1e4:.3f}   t = {d.mean()/se:+.2f}")

    print("\n  IV/RV by RV sampling step (stale 1s bars bias RV down):")
    for step, key in ((1, "rv"), (5, "rv5"), (15, "rv15")):
        v = np.array([r[key] for r in rows if r.get(key)])
        iv2 = np.array([r["iv"] for r in rows if r.get(key)])
        print(f"    RV at {step:2d}s: median IV/RV {np.median(iv2/v):.3f}   "
              f"share IV>RV {(iv2>v).mean()*100:5.1f}%   N={len(v):,}")

    print("\n  by symbol:")
    for s in sorted(set(r["sym"] for r in rows)):
        m = np.array([r["sym"] == s for r in rows])
        if m.sum() < 25:
            continue
        print(f"    {s:<9s} N={int(m.sum()):4d}  median IV/RV {np.median(ratio[m]):.3f}  "
              f"share IV>RV {(iv[m]>rv[m]).mean()*100:5.1f}%")


if __name__ == "__main__":
    main()
