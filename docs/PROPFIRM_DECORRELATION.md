# Smoothing the prop-account pack — measured, 2026-08-20

*Problem (Igor): "it's very lumpy and Sharpe is awful. I have a chance of buying 20 accounts and
getting nothing." Code: `scripts/propfirm_portfolio.py`.*

## 1. The lumpiness is correlation, not EV

20 accounts, minimum-trade policy, $94 fee each:

| rho | EV | sd | EV/sd | **P(nothing)** | median |
|---|---|---|---|---|---|
| 0.00 | 6405 | 7105 | **0.90** | **14.8%** | 6220 |
| 0.50 | 6212 | 13351 | 0.47 | 44.5% | 820 |
| 0.90 | 5995 | 21818 | 0.27 | 72.7% | −1880 |
| 1.00 | 6011 | 30452 | 0.20 | **91.0%** | −1880 |

**EV is flat in rho; only the shape moves.** Buying 20 accounts and getting nothing is a 91%
event when they are all the same trade and a 15% event when they are independent — same
expectancy, 4.5x the Sharpe. Scaling only helps after decorrelating: at rho=0, 40 accounts give
EV $12,570 and P(nothing) **2%**; at rho=0.9 the same 40 give P(nothing) **67%**.

*(This simplified model runs the funded leg 12 days and omits monthly fees, so per-account EV
~$315 is richer than the propsim minimum-trade figure of $161-199. The SHAPE is the output
here, not the level.)*

## 2. What rho is actually achievable — MEASURED on our own data

**Same instrument, disjoint intraday windows, same day** (NQ 5m, 2763 days):

|  | 09:30 | 10:00 | 11:00 | 13:00 | 14:30 |
|---|---|---|---|---|---|
| 09:30-10:00 | 1.000 | −0.005 | −0.001 | 0.011 | 0.024 |
| 10:00-10:30 | −0.005 | 1.000 | −0.019 | 0.003 | −0.002 |
| 11:00-11:30 | −0.001 | −0.019 | 1.000 | 0.005 | 0.042 |
| 13:00-13:30 | 0.011 | 0.003 | 0.005 | 1.000 | −0.030 |
| 14:30-15:00 | 0.024 | −0.002 | 0.042 | −0.030 | 1.000 |

**mean off-diagonal rho = +0.003, max |rho| = 0.042.** Essentially zero.

**Different instruments, daily RTH open->close** (1023 shared days):

|  | NQ | ES | GC | CL | SI |
|---|---|---|---|---|---|
| NQ | 1.000 | **0.939** | 0.149 | 0.078 | 0.262 |
| ES | 0.939 | 1.000 | 0.181 | 0.154 | 0.310 |
| GC | 0.149 | 0.181 | 1.000 | 0.201 | **0.807** |
| CL | 0.078 | 0.154 | 0.201 | 1.000 | 0.235 |
| SI | 0.262 | 0.310 | 0.807 | 0.235 | 1.000 |

### The ranking, and it is not what you would guess

1. **Time-stagger on one instrument: rho ~ 0.00.** The best lever, and it costs NOTHING —
   the windows are on the SAME day. This is the correction to the intuition that
   decorrelation must cost calendar time. It does not. RTH holds ~13 disjoint 30-min
   windows, so a dozen near-independent NQ accounts can run in a single session.
2. **NQ vs CL (0.078) or GC (0.149):** decent, but strictly worse than staggering.
3. **NQ vs ES (0.939) and GC vs SI (0.807): useless.** Running those pairs together buys
   almost no diversification — they are the same bet.

## 3. Jumps: the slide's claim does NOT hold for this geometry

Path engine validated against the exact Brownian law S/(S+T) first (max error 0.004).
Funded leg, risk $1,900 aiming +$5,100, total variance held constant:

| jumps/trade | jump sd | P(win) | vs Brownian |
|---|---|---|---|
| 0 | — | 0.276 | 1.000x |
| 1 | 0.5 | 0.273 | 0.990x |
| 2 | 0.7 | 0.277 | 1.005x |
| 8 | 1.5 | 0.351 | 1.274x |

At plausible intensities jumps are **neutral** (within noise); at extreme intensity they
**help**. Reason: the barriers are asymmetric — death is near ($1,900), payout is far
($5,100). Diffusion reaches the near barrier easily; the far one needs a big move, and jumps
supply big moves. "Jumps raise P(knockout), so Gaussian is an upper bound" is right when you
are LONG a knockout that gaps against you. Here the far barrier is the payoff, so gaps cut
both ways. **Do not apply a jump haircut to this structure without re-deriving it.**

A first version of this file reported a 1.01x haircut from a path engine that FAILED its own
validation (0.354 vs exact 0.271) because unresolved paths were settled by sign, which biases
badly when T >> S. Fixed by crediting unresolved paths the exact continuation probability
(x+S)/(S+T). **The validation block is the only reason that was caught.**

## 4. Caveats

- The correlation measured is on 30-min window RETURNS, i.e. direction, which is what decides
  win/lose. Volatility clustering IS shared across windows within a day, so it correlates the
  SPEED of resolution, not the outcome. Residual dependence is plausible but second-order.
- The minimum-trade policy needs a wide bracket (76-127 ticks). A 30-min window may be too
  short to resolve one; longer windows mean fewer disjoint slots per day. **Size the window to
  the bracket before assuming 13 slots.**
- Correlation is injected via a Gaussian copula on trade outcomes, not a shared price path, so
  tail co-movement is understated. High-rho P(nothing) figures are, if anything, optimistic.
- None of this creates drift. Correlation, tail hedging and diversification are all VARIANCE
  tools. The drift comes from the rulebook geometry (locked trail + must-remain buffer), and
  the unmeasured risk remains discretionary payout denial.
