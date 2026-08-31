"""
propfirm_portfolio.py — why a pack of prop accounts is lumpy, and what actually smooths it.

    python3 scripts/propfirm_portfolio.py

THE PROBLEM (Igor, 2026-08-20): "it's very lumpy and Sharpe is awful. I have a chance of
buying 20 accounts and getting nothing."

Correct, and the cause is not the EV — it is the CORRELATION between the accounts. Three
things modelled here that `propfirm_minimal_trades.py` does not:

  1. FAT TAILS AND JUMPS. propsim samples excursions from exact BROWNIAN first-passage laws.
     A trailing drawdown is a knockout barrier — a first-passage problem — so its value is
     set almost entirely by the tail, the exact part a Gaussian gets wrong. With jumps you
     GAP THROUGH the floor instead of walking into it, so P(knockout) rises and EV falls.
     The Gaussian number is an UPPER BOUND on the edge, not a central estimate.

  2. CORRELATION ACROSS ACCOUNTS. Correlation does NOT change E[passes]. That is a theorem,
     and it is why buying more accounts cannot raise expectancy. What it changes is the
     SHAPE: at rho=1 a 20-pack is one account with a 20x stake, so P(nothing) collapses to
     P(one account fails). Diversification is a VARIANCE tool, not an expectancy tool.

  3. THE FULL DISTRIBUTION. P(nothing), the median, and EV/sd decide whether this is a
     business or a lottery ticket. The mean hides all of it.

VALIDATION: the path engine is checked against the exact Brownian answer S/(S+T) in the
no-jump limit before any jump number is reported.
"""

import numpy as np
from math import erf, sqrt

STEPS = 3000
SQ2 = sqrt(2.0)


def _phi(z):
    """Standard normal CDF (vectorised, no scipy)."""
    return 0.5 * (1.0 + np.vectorize(erf)(z / SQ2))


# ---------------------------------------------------------------------------
# 1. Per-trade first passage under a jump-diffusion
# ---------------------------------------------------------------------------
def trade_outcome(S, T, n=120_000, jump_lam=0.0, jump_sd=0.0, seed=0):
    """
    P(hit +T before -S) for a driftless jump-diffusion, by direct path simulation.

    Total variance is held CONSTANT as jumps are added, so this isolates the effect of
    tail SHAPE rather than simply making the process louder. With jump_lam=0 it must
    reproduce the Brownian answer S/(S+T); that is the validation below.
    """
    rng = np.random.default_rng(seed)
    total_var = ((S + T) * 0.55) ** 2
    jvar = jump_lam * (jump_sd * S) ** 2
    diff_sd = sqrt(max(total_var - jvar, 1e-9) / STEPS)

    x = np.zeros(n)
    alive = np.ones(n, bool)
    win = np.zeros(n, bool)
    for _ in range(STEPS):
        step = rng.normal(0.0, diff_sd, n)
        if jump_lam > 0 and jump_sd > 0:
            nj = rng.poisson(jump_lam / STEPS, n)
            m = nj > 0
            if m.any():
                step[m] += rng.normal(0.0, jump_sd * S, m.sum()) * np.sqrt(nj[m])
        x = np.where(alive, x + step, x)
        hi, lo = alive & (x >= T), alive & (x <= -S)
        win |= hi
        alive &= ~(hi | lo)
        if not alive.any():
            break
    # Unresolved paths must NOT be settled by sign -- that biases badly when T >> S.
    # The exact Brownian continuation probability from position x is (x+S)/(S+T); use it
    # as a fractional credit. (Validation in main() is what proves this is right.)
    frac = np.clip((x[alive] + S) / (S + T), 0.0, 1.0) if alive.any() else np.array([])
    return float((win.sum() + frac.sum()) / len(x))


# ---------------------------------------------------------------------------
# 2. A pack of accounts, vectorised over (sims x accounts)
# ---------------------------------------------------------------------------
def simulate_pack(n_acct, rho, n_sims=8000, *, haircut=1.0, seed=1,
                  target=3000., mll=2000., cap=100., buffer=2100., overshoot=3000.,
                  eval_wins=2, split=0.90, fee=94.0, eval_days=12, fund_days=12):
    """
    `rho` is the correlation of the underlying moves the accounts are exposed to.
    rho=1 -> every account sees the same move (same instrument, same time, same side).
    rho=0 -> genuinely independent bets.
    `haircut` multiplies every win probability: the jump-model penalty from step 1.

    Returns net dollars per account, shape (n_sims, n_acct).
    """
    rng = np.random.default_rng(seed)
    M = n_sims * n_acct
    r = min(max(rho, 0.0), 1.0)

    def uniforms(days):
        zc = rng.standard_normal((n_sims, 1, days))
        zi = rng.standard_normal((n_sims, n_acct, days))
        z = sqrt(r) * zc + sqrt(1 - r) * zi
        return _phi(z).reshape(M, days)

    u_ev = uniforms(eval_days)
    u_fd = uniforms(fund_days)

    # ---- eval leg: one trade/day, risk = target/eval_wins, EOD trail capped at `cap`
    risk = target / eval_wins
    e = np.zeros(M)
    maxclose = np.zeros(M)
    floor = np.minimum(maxclose - mll, cap)
    alive = np.ones(M, bool)
    passed = np.zeros(M, bool)
    for d in range(eval_days):
        act = alive & ~passed
        if not act.any():
            break
        room = np.maximum(e - floor, 0.0)
        s_eff = np.minimum(risk, room)
        p = np.where(s_eff + risk > 0, s_eff / (s_eff + risk), 0.0) * haircut
        wins = u_ev[:, d] < p
        e = np.where(act, e + np.where(wins, risk, -s_eff), e)
        alive &= ~(act & (e <= floor))
        maxclose = np.where(act & alive, np.maximum(maxclose, e), maxclose)
        floor = np.minimum(maxclose - mll, cap)
        passed |= act & alive & (e >= target)

    # ---- funded leg: ONE trade at a time, aim buffer+overshoot, withdraw, repeat
    e = np.zeros(M)
    maxclose = np.zeros(M)
    floor = np.minimum(maxclose - mll, cap)
    alive = passed.copy()
    W = np.zeros(M)
    for d in range(fund_days):
        if not alive.any():
            break
        T = np.maximum((buffer + overshoot) - e, overshoot)
        room = np.maximum(e - floor, 0.0)
        s_eff = np.minimum(mll - 100.0, room)
        p = np.where(s_eff + T > 0, s_eff / (s_eff + T), 0.0) * haircut
        wins = u_fd[:, d] < p
        e = np.where(alive, e + np.where(wins, T, -s_eff), e)
        alive &= ~(e <= floor)
        maxclose = np.where(alive, np.maximum(maxclose, e), maxclose)
        floor = np.minimum(maxclose - mll, cap)
        pay = alive & (e - buffer >= 500)
        W = np.where(pay, W + (e - buffer), W)
        e = np.where(pay, buffer, e)

    net = W * split - fee
    return net.reshape(n_sims, n_acct)


def report(net, label):
    tot = net.sum(axis=1)
    n_acct = net.shape[1]
    spent = 0.0            # fee already netted inside
    passes = (net > 0).sum(axis=1)
    return dict(label=label, n=n_acct, ev=tot.mean(), sd=tot.std(),
                sharpe=tot.mean() / max(tot.std(), 1e-9),
                p_nothing=float((passes == 0).mean()),
                p_loss=float((tot <= 0).mean()),
                med=float(np.median(tot)),
                p05=float(np.percentile(tot, 5)),
                p95=float(np.percentile(tot, 95)),
                e_passes=float(passes.mean()))


def main():
    print("=" * 100)
    print("  1. VALIDATION — path engine vs the exact Brownian answer S/(S+T), no jumps")
    print("=" * 100)
    print(f"\n  {'S':>7} {'T':>7} {'exact':>8} {'simulated':>10} {'diff':>8}")
    print("  " + "-" * 50)
    ok = True
    for S, T in [(1500., 1500.), (1900., 5100.), (1900., 3000.), (600., 3000.)]:
        exact = S / (S + T)
        got = trade_outcome(S, T, seed=3)
        ok &= abs(got - exact) < 0.02
        print(f"  {S:>7.0f} {T:>7.0f} {exact:>8.3f} {got:>10.3f} {got-exact:>+8.3f}")
    print(f"\n  {'PASS' if ok else 'FAIL'} — engine reproduces the Brownian barrier law.")

    print("\n" + "=" * 100)
    print("  2. WHAT JUMPS DO TO THE BARRIER  (total variance held constant)")
    print("=" * 100)
    S, T = 1900., 5100.
    base = trade_outcome(S, T, seed=5)
    print(f"\n  funded leg, risk ${S:.0f} aiming +${T:.0f}. Brownian P(win) = {S/(S+T):.3f}")
    print(f"\n  {'jumps/trade':>12} {'jump sd':>9} {'P(win)':>8} {'vs Brownian':>12}")
    print("  " + "-" * 48)
    haircuts = {}
    for lam, jsd in [(0.0, 0.0), (0.5, 0.3), (1.0, 0.5), (2.0, 0.7), (4.0, 1.0)]:
        p = trade_outcome(S, T, jump_lam=lam, jump_sd=jsd, seed=5)
        h = p / base if base > 0 else 1.0
        haircuts[(lam, jsd)] = h
        print(f"  {lam:>12.1f} {jsd:>9.1f} {p:>8.3f} {h:>11.2f}x")
    print("\n  Jumps let price GAP THROUGH the floor instead of walking into it, so the")
    print("  knockout fires more often for the same target. Gaussian = upper bound.")

    print("\n" + "=" * 100)
    print("  3. CORRELATION — the answer to 'I could buy 20 and get nothing'")
    print("=" * 100)
    print("\n  20 accounts, $94 each (40% off), minimum-trade policy, no jumps.\n")
    print(f"  {'rho':>6} {'E[passes]':>10} {'EV':>8} {'sd':>8} {'EV/sd':>7} "
          f"{'P(nothing)':>11} {'median':>8} {'5th pct':>9} {'95th pct':>9}")
    print("  " + "-" * 92)
    for rho in (0.0, 0.25, 0.50, 0.75, 0.90, 0.97, 1.0):
        r = report(simulate_pack(20, rho, seed=11), f"rho={rho}")
        print(f"  {rho:>6.2f} {r['e_passes']:>10.2f} {r['ev']:>8.0f} {r['sd']:>8.0f} "
              f"{r['sharpe']:>7.2f} {r['p_nothing']:>10.1%} {r['med']:>8.0f} "
              f"{r['p05']:>9.0f} {r['p95']:>9.0f}")
    print("\n  E[passes] and EV are FLAT in rho. Only the shape moves. That is the theorem.")

    print("\n" + "=" * 100)
    print("  4. HOW MANY ACCOUNTS, at realistic correlation")
    print("=" * 100)
    print(f"\n  {'accounts':>9} " + "".join(f"{f'rho={r}':>13}" for r in (0.0, 0.5, 0.9)))
    print("  " + "-" * 60)
    for n in (1, 5, 10, 20, 40):
        cells = []
        for rho in (0.0, 0.5, 0.9):
            r = report(simulate_pack(n, rho, seed=13), "")
            cells.append(f"{r['ev']:>5.0f}/{r['p_nothing']:>5.0%}")
        print(f"  {n:>9d} " + "".join(f"{c:>13}" for c in cells))
    print("\n  cells are EV / P(nothing).")

    print("\n" + "=" * 100)
    print("  5. BOTH EFFECTS TOGETHER — jumps AND correlation")
    print("=" * 100)
    h = haircuts[(1.0, 0.5)]
    print(f"\n  20 accounts, jump haircut {h:.2f}x applied to every win probability.\n")
    print(f"  {'rho':>6} {'EV (gauss)':>11} {'EV (jumps)':>11} {'P(nothing) g':>13} "
          f"{'P(nothing) j':>13}")
    print("  " + "-" * 60)
    for rho in (0.0, 0.5, 0.9, 1.0):
        g = report(simulate_pack(20, rho, seed=17), "")
        j = report(simulate_pack(20, rho, haircut=h, seed=17), "")
        print(f"  {rho:>6.2f} {g['ev']:>11.0f} {j['ev']:>11.0f} "
              f"{g['p_nothing']:>12.1%} {j['p_nothing']:>12.1%}")


if __name__ == "__main__":
    main()
