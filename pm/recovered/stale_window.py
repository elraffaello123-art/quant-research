"""Stale-liquidity window: is there a retail-winnable speed race on Polymarket?

THE QUESTION
------------
After a market reprices (the world learned something), how long does liquidity keep
printing at the OLD price, and how many dollars of P&L sit in those prints?

That dollar figure is the entire pot a fast player is fighting over. It is measured
from the public trade tape alone -- no ground truth, no external feed, no venue bet.

THE FALSIFICATION
-----------------
The same statistic is computed at RANDOM timestamps in the same market (the placebo).
If real repricing events look like random moments, there is no event-latency structure
and the whole idea is dead. Crypto markets are included as a CONTROL: they are the known
contested category, so their number calibrates what "already lost" looks like.

KNOWN LIMITS (stated up front, not discovered later)
----------------------------------------------------
* The tape shows only trades that HAPPENED. Resting stale depth nobody hit is invisible.
  So this measures realised stale flow, not total available depth.
* data-api timestamps are unix SECONDS. We cannot see sub-second structure. That is fine
  for the decision at hand: we need to tell "0s window" (dead) from "10-60s window" (alive).
* Trade tape is taker-initiated prints. Direction is inferred from price movement, not
  from a signed aggressor flag.

Phase 0 of the script probes the endpoints and prints the actual JSON schema before
relying on any field, so a schema drift reports itself instead of crashing silently.
"""
import sys
import time
import random
import statistics
from collections import defaultdict

sys.path.insert(0, "/private/tmp/claude-501/-Users-igor-quant/2b1b240d-076c-4f6b-8817-f58d11c5f676/scratchpad")
import pmnet

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"

# Categories to sweep. crypto = the control (known contested).
CATEGORIES = ["crypto", "esports", "sports", "politics", "geopolitics"]

JUMP_CENTS = 0.03      # a repricing event = price moves at least this far ...
PERSIST_SEC = 120      # ... and is still moved this long afterwards
STALE_TOL = 0.01       # a print counts as "stale" if within this of the pre-event price
MAX_WINDOW = 300       # stop looking for stale prints this long after the event
N_PLACEBO = 5          # random non-event timestamps sampled per real event
SEED = 20260830        # fixed: no Math.random-style irreproducibility


# ---------------------------------------------------------------- phase 0: probe

def probe():
    print("=" * 72)
    print("PHASE 0  reachability + schema")
    print("=" * 72)
    ok = True
    for name, url in [
        ("gamma ", f"{GAMMA}/markets?limit=1&closed=true"),
        ("data  ", f"{DATA}/trades?limit=1"),
    ]:
        t = time.time()
        try:
            d = pmnet.get(url)
            print(f"  {name} OK  {round((time.time()-t)*1000)}ms")
            rec = d[0] if isinstance(d, list) and d else d
            if isinstance(rec, dict):
                print(f"         fields: {sorted(rec.keys())}")
        except Exception as e:
            ok = False
            print(f"  {name} FAIL  {type(e).__name__}: {e}")
    return ok


# ---------------------------------------------------------- market + tape access

def closed_markets(tag, want=25):
    """Closed, liquid markets in a category, newest first."""
    out, offset = [], 0
    while len(out) < want and offset < 500:
        url = (f"{GAMMA}/markets?closed=true&limit=100&offset={offset}"
               f"&order=volumeNum&ascending=false&tag_slug={tag}")
        try:
            batch = pmnet.get(url)
        except Exception as e:
            print(f"    ! {tag} offset {offset}: {type(e).__name__}: {e}")
            break
        if not batch:
            break
        for m in batch:
            try:
                vol = float(m.get("volumeNum") or m.get("volume") or 0)
            except (TypeError, ValueError):
                vol = 0.0
            cid = m.get("conditionId")
            if cid and vol >= 5000:
                out.append({"cid": cid, "slug": m.get("slug", "?"), "vol": vol,
                            "question": (m.get("question") or "")[:70]})
        offset += 100
        time.sleep(0.2)
    return out[:want]


def tape(cid, cap=4000):
    """Full trade tape for one market, normalised to YES probability, time-ascending."""
    rows, offset = [], 0
    while offset < cap:
        try:
            batch = pmnet.get(f"{DATA}/trades?market={cid}&limit=500&offset={offset}")
        except Exception:
            break
        if not batch:
            break
        for t in batch:
            try:
                p = float(t["price"])
                sz = float(t.get("size") or 0)
                ts = int(t["timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            # data-api returns BOTH tokens; normalise NO -> YES probability
            idx = t.get("outcomeIndex")
            if idx in (1, "1"):
                p = 1.0 - p
            if 0.0 < p < 1.0 and sz > 0:
                rows.append((ts, p, sz))
        if len(batch) < 500:
            break
        offset += 500
        time.sleep(0.15)
    rows.sort(key=lambda r: r[0])
    return rows


# ------------------------------------------------------------- the actual metric

def find_events(rows):
    """A repricing event: price moves >= JUMP_CENTS off its recent level and stays moved."""
    events = []
    n = len(rows)
    for i in range(5, n - 5):
        pre = statistics.median(p for _, p, _ in rows[max(0, i - 5):i])
        t0, p0, _ = rows[i]
        if abs(p0 - pre) < JUMP_CENTS:
            continue
        after = [p for ts, p, _ in rows[i:] if ts <= t0 + PERSIST_SEC]
        if len(after) < 3:
            continue
        # must still be beyond the halfway point of the jump
        if abs(statistics.median(after) - pre) < JUMP_CENTS / 2:
            continue
        if events and t0 - events[-1]["t0"] < PERSIST_SEC:
            continue  # one event per move, not one per print
        events.append({"i": i, "t0": t0, "p_old": pre, "p_new": p0})
    return events


def stale_pot(rows, i, t0, p_ref, p_new):
    """Dollars of P&L sitting in prints that still trade at p_ref after the market moved."""
    secs, dollars, pnl, cnt = 0.0, 0.0, 0.0, 0
    for ts, p, sz in rows[i + 1:]:
        if ts > t0 + MAX_WINDOW:
            break
        if abs(p - p_ref) <= STALE_TOL:
            secs = max(secs, ts - t0)
            dollars += sz * p
            pnl += sz * abs(p_new - p)
            cnt += 1
    return {"stale_sec": secs, "stale_$": dollars, "capturable_$": pnl, "n": cnt}


def placebo_pot(rows, rng):
    """Same statistic at a random moment -- the null. Pretend the price 'jumped' to the
    level it actually reaches PERSIST_SEC later, and measure the same way."""
    n = len(rows)
    if n < 30:
        return None
    i = rng.randrange(10, n - 10)
    t0, _, _ = rows[i]
    pre = statistics.median(p for _, p, _ in rows[i - 5:i])
    after = [p for ts, p, _ in rows[i:] if ts <= t0 + PERSIST_SEC]
    if len(after) < 3:
        return None
    return stale_pot(rows, i, t0, pre, statistics.median(after))


# ------------------------------------------------------------------------ driver

def main():
    if not probe():
        print("\nendpoints unreachable -- stopping before drawing conclusions")
        return
    rng = random.Random(SEED)
    summary = defaultdict(lambda: {"real": [], "null": [], "mkts": 0, "events": 0})

    for tag in CATEGORIES:
        print(f"\n{'='*72}\n{tag.upper()}\n{'='*72}")
        mkts = closed_markets(tag)
        print(f"  {len(mkts)} closed markets with volume >= $5k")
        for m in mkts:
            rows = tape(m["cid"])
            if len(rows) < 50:
                continue
            evs = find_events(rows)
            summary[tag]["mkts"] += 1
            for e in evs:
                r = stale_pot(rows, e["i"], e["t0"], e["p_old"], e["p_new"])
                if r["n"] == 0:
                    r["stale_sec"] = 0.0
                summary[tag]["real"].append(r)
                summary[tag]["events"] += 1
                for _ in range(N_PLACEBO):
                    q = placebo_pot(rows, rng)
                    if q:
                        summary[tag]["null"].append(q)
            if evs:
                med = statistics.median(
                    stale_pot(rows, e["i"], e["t0"], e["p_old"], e["p_new"])["capturable_$"]
                    for e in evs)
                print(f"    {len(rows):5d} trades  {len(evs):3d} events  "
                      f"med capturable ${med:8.2f}  {m['question']}")

    print(f"\n{'='*72}\nVERDICT  (crypto is the control: that is what 'already lost' looks like)\n{'='*72}")
    print(f"{'category':<12}{'mkts':>6}{'events':>8}{'med stale s':>13}"
          f"{'med $/event':>13}{'null $/event':>14}{'ratio':>8}")
    for tag in CATEGORIES:
        s = summary[tag]
        if not s["real"]:
            print(f"{tag:<12}{s['mkts']:>6}{0:>8}{'-':>13}{'-':>13}{'-':>14}{'-':>8}")
            continue
        msec = statistics.median(r["stale_sec"] for r in s["real"])
        mreal = statistics.median(r["capturable_$"] for r in s["real"])
        mnull = statistics.median(r["capturable_$"] for r in s["null"]) if s["null"] else 0.0
        ratio = (mreal / mnull) if mnull > 0 else float("inf")
        print(f"{tag:<12}{s['mkts']:>6}{s['events']:>8}{msec:>13.0f}"
              f"{mreal:>13.2f}{mnull:>14.2f}{ratio:>8.2f}")
    print("\nread it like this:")
    print("  ratio ~1.0        -> events look like random moments. no latency structure. dead.")
    print("  med stale s ~0    -> book reprices within the same second. you cannot get there. dead.")
    print("  $/event single $  -> real but too small to matter after infra + time.")
    print("  ratio >>1 AND tens of seconds AND meaningful $  -> a race worth entering.")


if __name__ == "__main__":
    main()
