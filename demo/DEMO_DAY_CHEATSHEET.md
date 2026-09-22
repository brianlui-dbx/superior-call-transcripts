# 🎤 Demo Day Cheat-Sheet — Genie One for Superior Plus Propane
**Anchor:** Retention-aware pricing — *"capture the pricing upside without buying it back in attrition."*
**Banner up:** Illustrative · NY/NJ · USD/gallons · synthetic rows labeled. **Native Genie One, 5 Agents.**
**Live-validated 2026-09-21** on production-scale data: **316 opps · 508 calls · 557 CX contacts · 858 deliveries.**

---

### The 7 questions — type verbatim, watch the route
*(bold = the live number to expect on stage)*

**① 2:00 — Baseline** → *Offer Blocker Agent*
> Which offer blockers affect the most Closed Lost opportunities in NY and NJ, and how does rate competitiveness (4A) rank?
- **Expect:** 6 blockers. **4B = 33 opps, 4A = 29 opps (2nd)**, then 4F 22 · 4E 21 · 4D 17 · 4C 15.
- **Beat:** 4A (rate) is a top-2 blocker. *"So just cut price? No — watch."*
- **Say it right:** ask "most Closed-Lost **opportunities**" (ranks by count; quoted-$ is sparse). Don't promise a dollar ranking.
- **Fallback:** open pinned Closed-Lost-by-blocker screenshot.

**② 4:00 — Service pain** → *CX & Service Recovery Agent*
> Average hold time and abandon rate by team in NY and NJ.
- **Expect:** 8 region×team rows. Hold **23–102s**, abandon **1.6–18.5%** — **NJ Inside Sales worst (101.7s / 18.5%)**, NY Retention best (1.6%).
- **Beat:** the lost accounts also had bad service. *"Different domain — same chat."*
- **Fallback:** restate "…by team and region."

**③ 6:30 — THE REVEAL** → *Customer Retention Decision Agent* ⭐
> NY and NJ opportunities with a rate objection (4A) AND a verified runout or late delivery in the last 90 days. Rank by contribution and show churn-risk tier.
- **Expect:** **76 accounts** (all **High** tier); top values **$23,795 (NY) / $18,093 (NJ)**. (Result shows 2 rows = NY/NJ grouping — say **"76 accounts."**)
- **Beat:** *price shock + verified service failure = the churn bomb.* **PAUSE.** *"One Agent — we pre-joined the domains into a governed metric view."*
- **Fallback:** pinned at-risk cohort table.

**④ 10:00 — Price posture** → *Retention Agent* (drill: *Pricing Position*)
> For those at-risk accounts, how far above the competitor rate are we quoting, and what's the fee load?
- **Expect:** quoting **~0.16 above competitor**, avg **fee load ~$22** (NY ~$22.8, NJ ~$21.7).
- **Beat:** *overpriced on the exact accounts we're failing to serve.*
- **Fallback:** Pricing Agent → "Avg Rate Gap by stage." *(If you see "fee load" reported in seconds, the metric-views job didn't redeploy the `Avg Fee Load` measure.)*

**⑤ 13:00 — THE DECISION** → *Customer Retention Decision Agent* ⭐
> Split my NY and NJ book into Can Raise vs Protect and show contribution at risk.
- **Expect:** **66 Can Raise vs 225 Protect**. Can-Raise = low/med risk, negative rate gap, no failures; Protect = high risk, positive gap, failures.
- **Beat:** *a defensible raise list and a protect list, evidence behind each name.*
- **Fallback:** pinned raise-vs-protect segment chart.

**⑥ 16:00 — Action** → *Retention Agent* (follow-up email)
> Draft a retention-first outreach for the top 5 Protect accounts, referencing the specific service issue — review only, do not send.
- **Expect:** top-5 Protect by contribution at risk: **$20,809 · $15,614 · $13,117 · $13,012 · $11,027**, each with its primary blocker.
- **Beat:** cites the *runout*, not just the objection. Insight → action.
- **Fallback:** pinned sample email.

**⑦ 18:00 — CFO close** → *Customer Retention Decision Agent* ⭐
> Net annual contribution at 0.5, 1, and 2 points of churn reduction — label every assumption.
- **Expect:** **$225K / $450K / $900K**, break-even **0.33pt**. *(Measure = $450K per full point; all illustrative, not booked EBITDA.)*
- **Close:** *"Capture the upside without buying it back in attrition — proven across four domains in one conversation. Nominate 2 districts, a Sales/Ops sponsor, a Finance owner — fixed budget, agreed measurement."*

---

### Routing map (⭐ = the pre-joined hub)
| # | Routes to | Live result |
|---|---|---|
| ① | Offer Blocker | 4B 33 / **4A 29** / 4F 22 / 4E 21 / 4D 17 / 4C 15 |
| ② | CX & Service Recovery | hold 23–102s · abandon 1.6–18.5% |
| ③ ⭐ | Customer Retention Decision | **76 accounts**, top $23,795 |
| ④ | Retention → drill Pricing Position | +0.16 rate gap · ~$22 fee load |
| ⑤ ⭐ | Customer Retention Decision | 66 Can Raise / 225 Protect |
| ⑥ | Customer Retention Decision | top-5 $20.8K→$11.0K |
| ⑦ ⭐ | Customer Retention Decision | $225K/$450K/$900K · BE 0.33pt |

### If it mis-routes
1. Restate using the Agent's own words (hold/abandon → CX; runout/late → Delivery; rate gap/fee → Pricing; raise/protect/contribution → Retention).
2. Still wrong → open the pinned fallback. **Never hand-wave.**

### "Is this real data?" (say it straight)
- **Real:** blocker codes + CX ops (hold/abandon/CSAT) — from the actual call feed.
- **Synthetic (labeled):** delivery/runouts, fees, contribution.
- **Illustrative scenario:** the $ economics — **not booked EBITDA.**
- Runout with no delivery record → Delivery Agent says **unverified** (show it — builds trust).

### Numbers to have cold
US Propane EBITDA ~$246M · Superior Delivers ≥$75M by 2028 (Customer Growth ~$30M) · demo scenario: 100K accts · $600/acct · $150K cost · **1pt ≈ $450K** · **2pt ≈ $900K net** · break-even **0.33pt** · reveal cohort **76 accounts / ~$134K contribution at risk**.
