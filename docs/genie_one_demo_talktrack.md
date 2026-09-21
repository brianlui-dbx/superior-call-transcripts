# Genie One — 20-Minute Demo Talk Track
**Superior Plus Propane · Retention-Aware Pricing · Native Genie One over 5 curated Genie Agents**

> Terminology per `databricks-agent-skills`: **Genie One** is the cross-data chat that **routes each question to the most relevant Genie Agent by its `description`**; the domains (CX, Delivery, Pricing, Retention, Offer Blocker) are curated **Genie Agents**. Native only — no Supervisor Agent / Agent Bricks.

**Setup before you start:** one Genie One conversation, warehouse warm, demo snapshot frozen, labeled fallback screenshot ready for every typed query. On-screen banner: **Illustrative scenario · NY/NJ · USD/gallons · synthetic rows labeled.** Audience: VP Sales/Ops in the room, CFO-minded exec on the line.
**Native routing rule enforced in the script:** every strategic/cross-domain question routes to the **Customer Retention Decision** Agent (over the governed `mv_retention` metric view, where the join is pre-computed). Single-domain questions route to their own Agent by description. No question relies on Genie live-joining two Agents.

---

### 0:00–2:00 · The tension (no tool yet)
**Say:** *"Your 2026 plan takes price to grow margin — and at the same time you're managing attrition and service pressure through the transformation. The danger is you take price on the exact accounts already wounded by a runout or a long call wait, and buy the increase back in churn. That decision lives in four systems today — CRM, the contact center, delivery, billing. Watch what happens when one Genie can see all four."* Show the 4-domain diagram for 20 seconds.

### 2:00–4:00 · Baseline on ground you already trust — *routes to the Offer Blocker Agent (existing, real)*
**Type:** `Which offer blockers are driving the most Closed Lost opportunity value in New York and New Jersey, and how does rate competitiveness (4A) rank?`
**Why it lands:** starts on the real, already-deployed Agent execs recognize. Establishes 4A (rate) as a top blocker → teases "so should we just cut price everywhere? No."

### 4:00–6:30 · Cross to service pain — *routes to the CX & Service Recovery Agent (real CXone fields, governed by mv_cx_service)*
**Type:** `For opportunities in NY and NJ, show average hold time, abandon rate, and repeat-contact rate by region and team.`
**Say aloud:** *"Different data domain — the contact center — same conversation. This is real data already in your call feed."* Reveals lost/at-risk accounts also had degraded service — first hint price isn't the whole story.

### 6:30–10:00 · THE REVEAL — *routes to the Customer Retention Decision Agent (mv_retention; join pre-computed)*
**Type:** `List NY and NJ opportunities that have a rate objection (4A) AND a verified runout or late delivery in the last 90 days. Rank by opportunity value and show the churn-risk tier.`
**Why it lands:** the payoff — **price shock stacked on a verified service failure = the churn bomb.** No single system answers it; the governed `mv_retention` metric view does. **Pause here.** Note: *"Genie answered this from one Agent because we pre-joined the domains into a governed metric view — that's how we keep it accurate, not a guess across silos."*

### 10:00–13:00 · Quantify the price posture — *stays in Retention Decision Agent (or drill to Pricing Position Agent)*
**Type:** `For those at-risk opportunities, how far above the competitor rate are we quoting, and what is their fee load?`
**Why it lands:** shows *we're overpriced vs market on the very accounts we're also failing to serve* — the setup for the decision. (If asked for raw extraction detail, drill into the **Pricing Position** space.)

### 13:00–16:00 · THE DECISION — *Customer Retention Decision Agent*
**Type:** `Split my NY and NJ book into two segments: accounts that can absorb a price increase — healthy CSAT, no runouts, small rate gap — versus accounts I must protect. Show the churn-risk tier and the evidence behind each.`
**Say:** *"This is the retention-aware pricing call — a defensible raise list and a protect list, with cross-domain evidence behind every name — made in one question."*

### 16:00–18:00 · Action — *reuses the follow-up-email capability, now cross-domain aware*
**Type:** `Draft a retention-first outreach for the top 5 protect accounts, referencing the specific service issue (runout or late delivery) on each — review only, do not send.`
**Why it lands:** closes insight → action using the asset already in the repo, now citing the runout, not just the objection. Shows Genie One drives work, not just charts.

### 18:00–20:00 · The CFO close — *Customer Retention Decision Agent (mv_retention scenario measures)*
**Type:** `Using the illustrative 100,000-account scenario at $600 contribution per retained account and $150,000 program cost, show net annual contribution at 0.5, 1, and 2 points of churn reduction, and the break-even. Label every assumption.`
**Expect:** ~**$150K / $450K / $1.05M**, break-even **0.25pt (250 accounts)**.
**Close on:** *"Capture the pricing upside without buying it back in attrition — and prove every account decision across four domains, in one conversation. Can we nominate two districts, a Sales/Ops sponsor, and a Finance owner to pilot it with a fixed budget and agreed measurement?"*

---

## Query-to-Agent routing cheat-sheet (rehearse these route correctly)
Genie One routes by each Agent's `description` — vocabulary below is chosen to match one Agent's description unambiguously.
| # | Time | Question intent | Routes to (Agent) |
|---|---|---|---|
| 1 | 2:00 | Blockers / Closed Lost value | Offer Blocker *(existing)* |
| 2 | 4:00 | Hold/abandon/repeat by team | CX & Service Recovery |
| 3 | 6:30 | 4A **+** verified runout (reveal) | **Customer Retention Decision** |
| 4 | 10:00 | Rate gap + fee load | Retention Decision → drill Pricing Position |
| 5 | 13:00 | Raise vs protect segmentation | **Customer Retention Decision** |
| 6 | 16:00 | Retention-first outreach draft | Retention Decision |
| 7 | 18:00 | $/churn-point sensitivity | **Customer Retention Decision** |

## Validated live answers (run against the deployed workspace, 2026-09-21)
Validated end-to-end on the production-scale dataset (**316 opportunities, 508 enriched calls, 557 CX contacts, 858 delivery orders**) in workspace `adb-7405615135791589`, catalog `brlui`. All 7 questions routed correctly and returned COMPLETED. Expected numbers to anticipate on stage:

| # | Routed to | Live result to expect |
|---|---|---|
| 1 | Offer Blocker | 6 blockers ranked; **4A = 29 Closed-Lost opps in NY/NJ (2nd, just behind 4B=33)** — establishes rate as a top-2 blocker without being the whole story. |
| 2 | CX & Service Recovery | 8 region×team rows; hold **23–102s**, abandon **1.6–18.5%** (NJ Inside Sales worst at 18.5%) — real service variation to point at. |
| 3 | Customer Retention Decision | **The reveal: 76 accounts** with 4A **+** a verified runout/late delivery, all **High** tier; top opp values **$23,795 (NY) / $18,093 (NJ)**. |
| 4 | Customer Retention Decision | At-risk NY/NJ quoted **~0.16 above competitor**, avg **fee load ~$22** (uses the added `Avg Fee Load` measure). |
| 5 | Customer Retention Decision | Book splits **66 "Can Raise" vs 225 "Protect"** (NY+NJ); Can-Raise = low/med risk, negative rate gap, no failures; Protect = high risk, positive gap, failures. |
| 6 | Customer Retention Decision | Top-5 Protect accounts by contribution at risk (**$20,809 / $15,614 / $13,117 / $13,012 / $11,027**), each with its primary blocker. |
| 7 | Customer Retention Decision | Scenario: **$225K / $450K / $900K** net at 0.5/1/2 pts; **break-even 0.33pt**. (Measure returns $450K per full point; label all as illustrative, not booked EBITDA.) |

**Reveal-beat framing:** `Rate Objection And Failure` = **76** and `Contribution At Risk` (Protect) = **~$134K** across NY/NJ — say "76 accounts where a price objection sits on top of a verified service failure — that's the churn bomb."

**Two rehearsal notes surfaced during validation:**
- **Q1 ranks by opportunity count, not dollars.** `final_quoted_rate.amount` is sparse, so Genie ranks blockers by affected-opportunity count and may say "ranked equally" on value. Ask for it as *"which blockers affect the most Closed-Lost opportunities"* to get the clean 4B=33 / 4A=29 ordering, or accept the count framing. Don't promise a dollar ranking here.
- **Q4 fee load** now resolves to the governed **`Avg Fee Load`** measure (added to `mv_retention` during validation). Before that fix Genie substituted `Avg Hold Seconds` — if you ever see hold-seconds reported as "fee load," the metric-views job didn't redeploy.

## Fallbacks & honesty
- If a query mis-routes live: restate with the Agent's own description vocabulary (cheat-sheet), or open the pinned fallback result. Never hand-wave a wrong route.
- Keep the labeled synthetic/illustrative banner visible. If asked "is this real data?" — CX + blocker signals are real from the call feed; delivery, fees, and contribution are synthetic and labeled; economics are an illustrative scenario, not booked EBITDA.
- If pushed on a runout with no delivery record, the Delivery Agent answers **unverified** — show it; it builds trust with the ops leader.
