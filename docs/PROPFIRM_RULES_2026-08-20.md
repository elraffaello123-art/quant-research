# Prop-firm rules reference — daily-payout generation, pulled 2026-08-20

*Snapshot, not a live feed. These pages change weekly. Re-verify before committing money.*
*Transcribed into `scripts/propfirm_daily_accounts.py`; priced by `scripts/propfirm_daily_mc.py`.*

All figures are the **$50K** size unless stated, so the comparison is like-for-like.

---

## The one structural fact that organises every account here

On all four firms, **the payout buffer equals the max loss limit plus $100** — which is
exactly the amount that trails the drawdown out to its permanent lock. So:

> You cannot withdraw a dollar until you have pushed the threshold to its floor, and once
> it is there, your remaining distance to death is **$100**.

The first payout and the trail-lock are the *same event*. Everything after it is played on a
$100 cushion. That is the geometry the daily-payout structure actually sells, and it is why
"daily payouts" is a much smaller gift than it sounds — you still have to travel the entire
MLL distance before the first cent comes out.

---

## MyFundedFutures — Rapid 50K  *(official help centre)*

`help.myfundedfutures.com/en/articles/13134709-rapid-plan-50k-a-comprehensive-look`

| | Evaluation | Sim-Funded |
|---|---|---|
| Profit target | $3,000 | — |
| Max loss limit | $2,000 | $2,000 from equity **high-water mark** |
| **Drawdown type** | **End-of-day trailing** | **Intra-day trailing** |
| Trail lock | at +$100 | at +$100, permanent |
| Daily loss limit | none | none |
| Min trading days | 2 | — |
| Consistency | 50% (eval only, soft) | **none** |
| Max contracts | 5 mini / 50 micro | 5 mini / 50 micro |
| T1 news | allowed | **banned**, flat 2 min either side |

Payouts: buffer **$2,100**, then **daily — every 24 hours**, first exactly 24h after the first
funded trade. Minimum **$500**, no stated cap. Split **90/10**. No activation fee.
Price **$157/month** (test-max; not on an official page). Rapid Live after a $10k net-profit day.

**The double switch on funding day** — drawdown flips EOD → intraday, *and* news trading flips
allowed → banned. Both get worse at the moment you start being paid.

## MyFundedFutures — Rapid EOD 50K  *(official help centre)*

`help.myfundedfutures.com/en/articles/16158363-rapid-eod-50k-a-comprehensive-look`

Identical target ($3,000) and MLL ($2,000). **Both stages trail end-of-day.** The safer
drawdown is not free — it is paid for in rules:

| | Rapid | Rapid EOD |
|---|---|---|
| funded drawdown | intraday | **EOD** |
| min trading days | 2 | **4** |
| eval consistency | 50% | **30%** |
| max contracts | 5 mini | **3 mini** |
| payout cycle | daily | daily, **$500 net profit since last payout** |

Buffer $2,100, min payout $500, uncapped, 90/10. Inactivity rule: 7 days.
Described by third parties as a **limited-time offer** — may not be purchasable.

---

## LucidDaily 50K  *(third-party only — weakest provenance in this file)*

Launched July 2026. Unique: **you choose the eval drawdown type and the DLL at checkout**,
four combinations at four prices. The config locks when you buy.

Prices (list → with 40% VIBES code), $50K:

| config | list | discounted |
|---|---|---|
| Intraday + DLL on | $136 | $81.60 |
| Intraday + DLL off | $156 | $93.60 |
| EOD + DLL on | $165 | $99.00 |
| EOD + DLL off | $185 | $111.00 |

Eval: target $3,000, MLL $2,000 (trails to +$100 then locks), consistency **50% (eval only)**,
max 4 mini / 40 micro. DLL when on: **$1,200**, soft breach (locked out, not blown).

**Funded is always intraday trailing regardless of the toggle.** So the EOD premium buys
*eval survival only* — a fact worth knowing before paying $29.40 extra for it.

Payouts: **daily requests**, no windows, no minimum profitable days. Minimum **$500**.
Buffer **$52,100 non-withdrawable** (= start + MLL + $100) — Lucid states explicitly that the
buffer must *remain*, unlike MFFU. No per-request cap. Split **90/10**. No funded consistency.
Red-folder news is a **hard breach that ends the account**. Sim profit payout capped at
$15,000 total at live transition.

Other Lucid families: LucidPro (structured eval, EOD DD, funded consistency), LucidFlex
(EOD DD, no DLL funded), LucidDirect (instant, 20% consistency).

---

## Tradeify — Select Daily 50K  *(help centre 403'd; via propdatalab)*

Select eval: **$165** ($95 reset). Target $3,000, MLL **$2,000 EOD trailing**, no DLL,
min **3** trading days (forced by the consistency rule), **40% consistency (eval only)**.

Funded — a **permanent choice** between Select Flex and Select Daily:

| | Select Flex | **Select Daily** |
|---|---|---|
| payout cadence | every 5 winning days | **daily (24h guarantee)** |
| daily loss limit | none | **$1,000** |
| buffer | none stated | **$2,100 must remain** |
| max payout / cycle | $3,000 | **$1,000** |
| withdrawal limit | 50% of profits | **2× profit since last payout** |
| min payout | not specified | $250 |

Both: split 90/10 from the first payout, no funded consistency. Drawdown trails EOD and locks
at start + $100 once EOD balance exceeds start + MLL + $100.

Also: Growth ($145 / $95 reset, $1,250 DLL, 35% funded consistency, 5-winning-day payouts) and
Lightning (instant, $492 at 50K, no resets, progressive 20/25/30% consistency).

**Rule that may disqualify a coinflip outright:** >50% of trades *and* >50% of profit must come
from positions held **longer than 10 seconds**. Hedging banned. Auto-flatten 4:45 PM ET.
News trading explicitly unrestricted. Current promo code AUG, 40% off.

---

## Take Profit Trader 50K  *(third-party; no official page retrieved)*

**Test (eval):** $180/month. Target $3,000 (6%), MLL $2,000, **EOD trailing**, no DLL
(removed Jan 2025), min **5** trading days, **50% consistency**, max 6 mini / 60 micro.
News trading unrestricted during the Test.

**PRO (sim-funded):** one-time activation **$130**. Drawdown flips to **intraday trailing** —
described by TPT-focused guides as "the single biggest rule change between stages and the most
common reason funded accounts get liquidated." Split **80/20**. Day-one payouts, unlimited
frequency, minimum $250 fee-free.

**The buffer trap:** you must build profit equal to the max drawdown before full-rate
withdrawals — and *inside* the buffer zone the split **drops to 50%** if the account has been
active fewer than **60 trading days**. A coinflip campaign is always inside that window, so the
effective split is probably 0.50, not 0.80. Must be flat 1 min around FOMC/NFP. Max 5 PRO
accounts. Reset $399–$1,499.

**PRO+ (live):** invitation after ~$5,000 cumulative PRO profit. Split 90/10, drawdown reverts
to **EOD**, buffer eliminated.

---

## Cross-firm summary

| | MFFU Rapid | MFFU Rapid EOD | LucidDaily | Tradeify Select Daily | TPT PRO |
|---|---|---|---|---|---|
| eval fee | $157/mo | $157/mo | $81.60–$111 | $165 ($95 reset) | $180/mo + $130 |
| target | $3,000 | $3,000 | $3,000 | $3,000 | $3,000 |
| MLL | $2,000 | $2,000 | $2,000 | $2,000 | $2,000 |
| eval DD | EOD | EOD | **toggle** | EOD | EOD |
| **funded DD** | **intraday** | **EOD** | **intraday** | **EOD** | **intraday** |
| min days | 2 | 4 | 0 | 3 | 5 |
| eval consistency | 50% | 30% | 50% | 40% | 50% |
| funded consistency | none | none | none | none | none |
| split | 90/10 | 90/10 | 90/10 | 90/10 | 80/20 (or 50%) |
| buffer | $2,100 reach | $2,100 reach | $2,100 **remain** | $2,100 **remain** | $2,000 |
| payout min | $500 | $500 | $500 | $250 | $250 |
| payout cap | none | none | none | **$1,000/cycle** | none |

**Every firm converges on the same core geometry**: $3,000 target, $2,000 MLL, trail-to-+$100,
$2,100 buffer, 90/10. They compete on *drawdown type*, *minimum days*, *consistency percentage*,
and *payout caps* — which is precisely the set of frictions that decide whether the structure is
worth buying, because the barrier geometry itself is identical across all of them.

---

## Rules that name this strategy (the dominant risk, not a footnote)

- **MFFU** — bans "exploiting the lack of slippage… tight brackets"; Terms demand "consistency
  in position sizing, trade frequency, and overall risk exposure."
- **Tradeify** — the >10-second holding-period rule is a direct mechanical block on fast
  bracket scalping; max contract size and DCA "discouraged."
- **Lucid** — red-folder news is a hard breach.
- **TPT** — the sub-60-trading-day 50% split penalises exactly the fast in-and-out campaign.

`p_payout_denied` is modelled at 0.0 so the raw geometry is visible, then swept. Any EV quoted
at p=0 is an **upper bound that assumes these clauses are never enforced** — which is not what
they are for.
