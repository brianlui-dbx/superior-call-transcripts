# Genie One — 10-Minute Demo Talk Track

**Superior Plus Propane · Retention-aware pricing · Genie One over five curated Genie Agents**

## The story in one sentence

> Genie One turns an ambiguous pricing decision into an evidence-backed action by combining governed data across sales, service, delivery, and pricing, grounding it in a Google Drive document, and then creating and scheduling the deliverable.

This version deliberately uses only **two analytical turns**: one hero question and one evidence drill-down. Protect the cross-domain reveal; do not add the old seven-question tour back in.

## Pre-flight

- Start in a fresh Genie One conversation with the warehouse warm.
- Confirm the **Google Drive MCP** connection is authorized and that the Google Doc **Superior Plus 2026 Pricing Plan (DEMO)** is in the connected Drive (https://docs.google.com/document/d/1FUk24Sb55As4WUOy9fe-cWFY_4noiwBGyRXZ9beISGs/edit).
- Confirm **Documents** and **Scheduled tasks** are enabled for this workspace/user. These are Genie One capabilities; do not attempt them from inside a curated Genie Agent page.
- Freeze the demo snapshot and keep the banner visible: **Illustrative scenario · NY/NJ · USD/gallons · synthetic rows labeled.**
- Have four fallbacks ready: the Drive excerpt, hero-query result, finished document, and scheduled-task confirmation.
- Use the validated snapshot as the expected result: 316 opportunities, 508 calls, 557 CX contacts, and 858 delivery orders.

### Workspace instructions

Upload [`genie_workspace_instructions.md`](genie_workspace_instructions.md) to Genie One before rehearsing. The pricing policy lives in the Google Doc **Superior Plus 2026 Pricing Plan (DEMO)** (https://docs.google.com/document/d/1FUk24Sb55As4WUOy9fe-cWFY_4noiwBGyRXZ9beISGs/edit); keep [`Superior_Plus_2026_Pricing_Plan_DEMO.md`](Superior_Plus_2026_Pricing_Plan_DEMO.md) as the repo source of that doc's content.

The instructions provide stable defaults, disjoint routing vocabulary, response formatting, and safe action behavior. They deliberately exclude the Protect/Can Raise rule, current counts, account lists, thresholds, and policy excerpts. Those must be reasoned over or retrieved fresh, preserving the demo's ambiguous-question moment.

## Run of show

| Time | Beat | What the audience should remember |
|---|---|---|
| 0:00–0:45 | Frame the decision | A price increase is not one database question. |
| 0:45–1:45 | Google Drive MCP | Genie can bring unstructured business context into the work. |
| 1:45–5:15 | Cross-domain hero question | Genie resolves an ambiguous request across four governed domains. |
| 5:15–6:30 | Evidence drill-down | The recommendation is inspectable, not a black box. |
| 6:30–7:45 | Create a document | Analysis becomes a shareable executive artifact. |
| 7:45–8:45 | Create a scheduled task | The work repeats without someone rebuilding it. |
| 8:45–10:00 | Recap and close | Context → decision → artifact → recurring operating rhythm. |

## Minute-by-minute talk track

### 0:00–0:45 — Frame the decision

**Say:**

> “Superior wants to grow margin through pricing without buying the increase back in churn. The hard question is not ‘who pays the most?’ It is ‘which accounts can absorb an increase, which should we protect, and why?’ Answering that spans CRM, contact-center experience, delivery reliability, pricing, and the current pricing policy.”

> “I’ll ask that question the way an executive actually would—without specifying tables, joins, or even a precise definition of ‘protect.’”

**Land:** This is intentionally complex and ambiguous, not a canned KPI lookup.

### 0:45–1:45 — Bring in business context with one MCP

**Type:**

> `Using the Google Drive MCP, find the Google Doc titled "Superior Plus 2026 Pricing Plan (DEMO)". Pull the section that defines the 2026 pricing objective and any customer-protection guardrails. Use it as context for this conversation, and cite the file. Do not search any other external source.`

**While it works, say:**

> “The policy does not need to be copied into a prompt or ingested into a new pipeline. Genie One calls one governed tool—Google Drive—and brings the current business language into the analysis with its source attached.”

**Show:** The file name, relevant excerpt, and citation. Do not read the whole document.

**Land:** MCP supplies current unstructured context; Unity Catalog data supplies the governed facts. Be precise that Drive is context, not a fifth analytical table.

### 1:45–5:15 — Ask one ambiguous, cross-domain hero question

**Type:**

> `Given that pricing objective, which NY and NJ accounts should we protect before the next price action, and which can absorb an increase? Work out a defensible definition of “protect,” explain it, rank the protect accounts by contribution at risk, and support each recommendation with the strongest available evidence across sales objections, contact-center experience, delivery reliability, and pricing. Clearly distinguish verified facts, inferred recommendations, and synthetic or illustrative inputs.`

**While it plans, say:**

> “I did not tell Genie what ‘protect’ means or which data to join. It has to turn an executive question into an analytical plan, route to the Customer Retention Decision Agent, and use the governed retention metric view that brings the four domains together at account grain.”

**On the result, point out only three things:**

1. **The interpretation:** Genie explains how it operationalized “protect”—for example, service failure, adverse rate gap, customer friction, and churn-risk tier.
2. **The cross-domain evidence:** a rate objection from sales, hold/abandon or repeat-contact signal from CX, verified runout/late delivery from operations, and rate gap/fee load from pricing.
3. **The decision:** a ranked protect cohort and a can-raise cohort, with assumptions and synthetic fields labeled.

**Expected anchors from the validated snapshot:**

- **225 Protect / 66 Can Raise** across NY and NJ.
- **76 accounts** combine a 4A rate objection with a verified runout or late delivery.
- The at-risk cohort is quoted about **$0.16 above competitor** with about **$22 average fee load**.
- Protect contribution at risk is approximately **$134K** in this illustrative snapshot.

**Say:**

> “This is the cross-domain moment: a price objection alone does not tell us to protect an account, and a runout alone does not set price posture. The combination changes the decision. Genie makes the ambiguity explicit, then answers with evidence rather than hiding it.”

**Land:** One conversation answers a decision no individual source can answer.

### 5:15–6:30 — Drill into evidence, not another dashboard

**Type:**

> `For the top three Protect accounts, show the evidence chain in a compact table: account, recommendation, sales signal, CX signal, verified delivery event, pricing signal, and source status. If evidence is missing or only synthetic, say so rather than filling the gap.`

**Show:** Expand one row/source citation or the generated SQL lineage; do not narrate all three accounts.

**Say:**

> “This is how we keep an agentic answer trustworthy. A recommendation remains separable from the facts behind it, missing evidence stays missing, and a delivery failure is called verified only when an operational record exists.”

**Land:** Complex reasoning remains auditable.

### 6:30–7:45 — Create one executive document

From the **Genie One conversation**, type:

> `Create a one-page document titled “NY/NJ Pricing Protection Brief.” Include the pricing objective from the cited Drive file, the Protect versus Can Raise summary, the top three Protect accounts with their evidence, recommended next actions, and a footer labeling synthetic and illustrative inputs. Keep it executive-ready and do not send it.`

**Show:** The created document/canvas. Point to the title, recommendation table, Drive citation, and assumptions footer.

**Say:**

> “The answer is no longer trapped in chat. Genie has converted the analysis into a governed, shareable working document, with the source context and caveats carried forward.”

**Land:** Analysis becomes a usable artifact without manual copy/paste.

### 7:45–8:45 — Create one scheduled task

**Type:**

> `Create a scheduled task for every Monday at 8:00 AM Eastern named “NY/NJ Pricing Protection Brief.” Refresh this analysis using the latest governed data and the same cited Drive policy, update the document, and notify me with the link. Do not send it to any other recipient.`

**Show:** The task confirmation, schedule, timezone, inputs, and recipient. Stop after creation; do not edit settings live.

**Say:**

> “This turns a one-time demo into an operating rhythm. Every Monday, the same governed question is refreshed against current data and the current policy, with a human still owning the resulting pricing decision.”

**Land:** Scheduled tasks operationalize the insight; they do not automate the final business decision.

### 8:45–10:00 — Recap and close

**Say:**

> “In under ten minutes, Genie One retrieved current policy through one MCP, resolved an ambiguous question across four governed data domains, exposed its evidence, created the executive brief, and scheduled the refresh.”

> “The value is not another chatbot or dashboard. It is a governed path from scattered context to a repeatable decision. The next step is a two-district pilot with Sales/Ops and Finance agreeing on the protection rule and the outcome measure.”

Then stop. Use remaining time as latency buffer or transition to Q&A.

## Presenter guardrails

- Do not run the former baseline, CX, price-posture, segmentation, outreach, and CFO questions separately. Their substance is now folded into the hero question.
- Say **“pre-joined governed metric view”**, not “Genie dynamically joined five agents.” Genie One routes the cross-domain question to the Retention Agent; the reliable cross-domain join already exists in `mv_retention`.
- Say **“Google Drive provides policy context”**, not “Drive data was ingested into Unity Catalog.”
- Do not claim the system predicts churn. The tier is rule-based, and the recommendation is an inference.
- Be explicit: blocker and CX signals are real; delivery, fees, contribution, and economics contain labeled synthetic/illustrative data.
- If document creation or scheduling is unavailable in the workspace, show the pre-created artifact/confirmation and describe the capability. Do not attempt it inside a curated Agent page.
- If asked why the workspace instructions help, say: **“They reduce repeated setup, routing ambiguity, and unnecessary agent fan-out; governed data and current policy are still retrieved fresh.”**

## Fallback sequence

1. **Drive MCP is slow:** open the saved excerpt and say it was retrieved in pre-flight through the same connection.
2. **Hero query is slow or mis-routes:** open the pinned result; do not burn time rephrasing more than once.
3. **Document creation is slow:** open the pre-created `NY/NJ Pricing Protection Brief`.
4. **Task creation is unavailable:** show the pre-created paused task and its schedule; do not imply a new task was created live.

## Cut line if running late

At 7:30, stop analytical exploration. Show the pre-created document for 20 seconds, create/show the scheduled task, and deliver the close. Never cut the hero cross-domain question.
