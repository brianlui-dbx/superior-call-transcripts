# Genie One — 10-Minute Demo Talk Track

**Superior Plus Propane · Retention-aware pricing · Genie One over five curated Genie Agents**

## The story in one sentence

> Genie One moves from focused offer-blocker intelligence to an ambiguous pricing decision, combining governed data across sales, service, delivery, and pricing, grounding it in a Google Drive document, and then creating and scheduling the deliverable.

This version deliberately uses **two questions and one evidence follow-up**: a fast single-domain question, the cross-domain hero question, and a compact drill-down. The contrast makes Genie One's routing visible without restoring the old seven-question tour.

## Pre-flight

- Start in a fresh Genie One conversation with the warehouse warm.
- Confirm the **Google Drive MCP** connection is authorized and that the Google Doc **Superior Plus 2026 Pricing Plan (DEMO)** is in the connected Drive (https://docs.google.com/document/d/1FUk24Sb55As4WUOy9fe-cWFY_4noiwBGyRXZ9beISGs/edit).
- Confirm **Documents** and **Scheduled tasks** are enabled for this workspace/user. These are Genie One capabilities; do not attempt them from inside a curated Genie Agent page.
- Freeze the demo snapshot and keep the banner visible: **Illustrative scenario · NY/NJ · USD/gallons · synthetic rows labeled.**
- Have four fallbacks ready: the blocker result, hero result with Drive citation, finished document, and scheduled-task confirmation.
- Use the validated snapshot as the expected result: 316 opportunities, 508 calls, 557 CX contacts, and 858 delivery orders.

### Workspace instructions

Upload [`genie_workspace_instructions.md`](genie_workspace_instructions.md) to Genie One before rehearsing. The pricing policy lives in the Google Doc **Superior Plus 2026 Pricing Plan (DEMO)** (https://docs.google.com/document/d/1FUk24Sb55As4WUOy9fe-cWFY_4noiwBGyRXZ9beISGs/edit); keep [`Superior_Plus_2026_Pricing_Plan_DEMO.md`](Superior_Plus_2026_Pricing_Plan_DEMO.md) as the repo source of that doc's content.

The instructions provide stable defaults, disjoint routing vocabulary, response formatting, and safe action behavior. They deliberately exclude the Protect/Can Raise rule, current counts, account lists, thresholds, and policy excerpts. Those must be reasoned over or retrieved fresh, preserving the demo's ambiguous-question moment.

## Run of show

| Time | Beat | What the audience should remember |
|---|---|---|
| 0:00–0:40 | Frame the decision | Start focused, then widen to the real business decision. |
| 0:40–1:50 | Single-domain blocker intelligence | Genie routes a focused question to the specialist domain. |
| 1:50–5:20 | Cross-domain hero + Drive MCP | Genie adds current policy context and resolves an ambiguous request across four governed domains. |
| 5:20–6:20 | Evidence drill-down | The recommendation is inspectable, not a black box. |
| 6:20–7:35 | Create a document | Analysis becomes a shareable executive artifact. |
| 7:35–8:35 | Create a scheduled task | The work repeats without someone rebuilding it. |
| 8:35–10:00 | Recap and close | Focused insight → contextual decision → artifact → operating rhythm. |

## Minute-by-minute talk track

### 0:00–0:40 — Frame the decision

**Say:**

> “Superior wants to grow margin through pricing without buying the increase back in churn. The hard question is not ‘who pays the most?’ It is ‘which accounts can absorb an increase, which should we protect, and why?’ Answering that spans CRM, contact-center experience, delivery reliability, pricing, and the current pricing policy.”

> “I’ll start with one focused sales question, then ask the question the way an executive actually would—without specifying tables, joins, or even a precise definition of ‘protect.’”

**Land:** This is intentionally complex and ambiguous, not a canned KPI lookup.

### 0:40–1:50 — Question 1: single-domain offer-blocker intelligence

**Type:**

> `Across NY and NJ Closed Lost opportunities, what are the leading offer blockers? Separate hard blockers and friction from issues that were merely mentioned or resolved, and include one supporting customer quote for the leading true blocker.`

**While it works, say:**

> “This is intentionally narrow. Genie routes it directly to Offer Blocker Analytics, where blocker codes, dispositions, and transcript evidence live. Notice the distinction between something a customer mentioned and something that actually blocked the offer.”

**Show:** The ranked blockers, the disposition split, and one quote. Do not expand into CX, delivery, or pricing yet.

**Land:** Genie answers a focused question through the narrowest governed specialist; the next question changes the scope and the route.

### 1:50–5:20 — Question 2: cross-domain hero question with Drive context

**Type:**

> `Using the Google Drive MCP, retrieve and cite the Google Doc titled "Superior Plus 2026 Pricing Plan (DEMO)" and use its pricing objective and customer-protection guardrails as context. Then determine which NY and NJ accounts we should protect before the next price action and which can absorb an increase. Work out a defensible definition of “protect,” explain it, rank the Protect accounts by contribution at risk, and support each recommendation with the strongest available evidence across sales objections, contact-center experience, delivery reliability, and pricing. Clearly distinguish verified facts, inferred recommendations, and synthetic or illustrative inputs. Do not search any other external source.`

**While it plans, say:**

> “The question has now widened. Genie retrieves the current policy through one governed Google Drive tool, then routes the analytical decision to Customer Retention Decision. I did not tell it what ‘protect’ means or which data to join; the governed retention metric view already brings the four domains together at account grain.”

**On the result, point out only four things:**

1. **The document context:** the cited Drive file and the specific objective/guardrails used.
2. **The interpretation:** Genie explains how it operationalized “protect”—for example, service failure, adverse rate gap, customer friction, and churn-risk tier.
3. **The cross-domain evidence:** a rate objection from sales, hold/abandon or repeat-contact signal from CX, verified runout/late delivery from operations, and rate gap/fee load from pricing.
4. **The decision:** a ranked protect cohort and a can-raise cohort, with assumptions and synthetic fields labeled.

**Expected anchors from the validated snapshot:**

- **225 Protect / 66 Can Raise** across NY and NJ.
- **76 accounts** combine a 4A rate objection with a verified runout or late delivery.
- The at-risk cohort is quoted about **$0.16 above competitor** with about **$22 average fee load**.
- Protect contribution at risk is approximately **$134K** in this illustrative snapshot.

**Say:**

> “This is the cross-domain moment: a price objection alone does not tell us to protect an account, and a runout alone does not set price posture. The combination changes the decision. Genie makes the ambiguity explicit, then answers with evidence rather than hiding it.”

**Land:** Drive supplies current policy context; governed Unity Catalog data supplies the analytical facts. Together they support a decision no individual source can answer.

### 5:20–6:20 — Drill into evidence, not another dashboard

**Type:**

> `For the top three Protect accounts, show the evidence chain in a compact table: account, recommendation, sales signal, CX signal, verified delivery event, pricing signal, and source status. If evidence is missing or only synthetic, say so rather than filling the gap.`

**Show:** Expand one row/source citation or the generated SQL lineage; do not narrate all three accounts.

**Say:**

> “This is how we keep an agentic answer trustworthy. A recommendation remains separable from the facts behind it, missing evidence stays missing, and a delivery failure is called verified only when an operational record exists.”

**Land:** Complex reasoning remains auditable.

### 6:20–7:35 — Create one executive document

From the **Genie One conversation**, type:

> `Create a one-page document titled “NY/NJ Pricing Protection Brief.” Include the pricing objective from the cited Drive file, the Protect versus Can Raise summary, the top three Protect accounts with their evidence, recommended next actions, and a footer labeling synthetic and illustrative inputs. Keep it executive-ready and do not send it.`

**Show:** The created document/canvas. Point to the title, recommendation table, Drive citation, and assumptions footer.

**Say:**

> “The answer is no longer trapped in chat. Genie has converted the analysis into a governed, shareable working document, with the source context and caveats carried forward.”

**Land:** Analysis becomes a usable artifact without manual copy/paste.

### 7:35–8:35 — Create one scheduled task

**Type:**

> `Create a scheduled task for every Monday at 8:00 AM Eastern named “NY/NJ Pricing Protection Brief.” Refresh this analysis using the latest governed data and the same cited Drive policy, update the document, and notify me with the link. Do not send it to any other recipient.`

**Show:** The task confirmation, schedule, timezone, inputs, and recipient. Stop after creation; do not edit settings live.

**Say:**

> “This turns a one-time demo into an operating rhythm. Every Monday, the same governed question is refreshed against current data and the current policy, with a human still owning the resulting pricing decision.”

**Land:** Scheduled tasks operationalize the insight; they do not automate the final business decision.

### 8:35–10:00 — Recap and close

**Say:**

> “In under ten minutes, Genie One answered a focused blocker question through the right specialist, retrieved current policy through one MCP, resolved an ambiguous question across four governed data domains, created the executive brief, and scheduled the refresh.”

> “The value is not another chatbot or dashboard. It is a governed path from scattered context to a repeatable decision. The next step is a two-district pilot with Sales/Ops and Finance agreeing on the protection rule and the outcome measure.”

Then stop. Use remaining time as latency buffer or transition to Q&A.

## Presenter guardrails

- Keep Question 1 strictly inside offer-blocker intelligence. Do not add CX, delivery, or pricing evidence until Question 2; the routing contrast is part of the story.
- Do not run the former baseline, CX, price-posture, segmentation, outreach, and CFO questions separately. Their substance is folded into the hero question.
- Say **“pre-joined governed metric view”**, not “Genie dynamically joined five agents.” Genie One routes the cross-domain question to the Retention Agent; the reliable cross-domain join already exists in `mv_retention`.
- Say **“Google Drive provides policy context”**, not “Drive data was ingested into Unity Catalog.”
- Do not claim the system predicts churn. The tier is rule-based, and the recommendation is an inference.
- Be explicit: blocker and CX signals are real; delivery, fees, contribution, and economics contain labeled synthetic/illustrative data.
- If document creation or scheduling is unavailable in the workspace, show the pre-created artifact/confirmation and describe the capability. Do not attempt it inside a curated Agent page.
- If asked why the workspace instructions help, say: **“They reduce repeated setup, routing ambiguity, and unnecessary agent fan-out; governed data and current policy are still retrieved fresh.”**

## Fallback sequence

1. **Blocker query is slow:** open the pinned single-domain result and preserve time for the hero question.
2. **Drive MCP or hero query is slow:** open the pinned hero result with its saved Drive citation; do not burn time rephrasing more than once.
3. **Document creation is slow:** open the pre-created `NY/NJ Pricing Protection Brief`.
4. **Task creation is unavailable:** show the pre-created paused task and its schedule; do not imply a new task was created live.

## Cut line if running late

At 7:30, stop analytical exploration. Show the pre-created document for 20 seconds, create/show the scheduled task, and deliver the close. Never cut the hero cross-domain question.
