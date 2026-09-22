# Demo Day Cheat Sheet — Genie One in 10 Minutes

**Anchor:** Capture pricing upside without buying it back in attrition.

**Banner:** Illustrative · NY/NJ · USD/gallons · synthetic rows labeled.

## Five prompts, typed verbatim

### 0:45 — Google Drive MCP

> Using the Google Drive MCP, find the Google Doc titled "Superior Plus 2026 Pricing Plan (DEMO)". Pull the section that defines the 2026 pricing objective and any customer-protection guardrails. Use it as context for this conversation, and cite the file. Do not search any other external source.

Show only the file, excerpt, and citation.

### 1:45 — Cross-domain hero question

> Given that pricing objective, which NY and NJ accounts should we protect before the next price action, and which can absorb an increase? Work out a defensible definition of “protect,” explain it, rank the protect accounts by contribution at risk, and support each recommendation with the strongest available evidence across sales objections, contact-center experience, delivery reliability, and pricing. Clearly distinguish verified facts, inferred recommendations, and synthetic or illustrative inputs.

Expected anchors: **225 Protect / 66 Can Raise · 76 objection + service-failure accounts · ~$0.16 rate gap · ~$22 fee load · ~$134K contribution at risk.**

Say: “A price objection alone does not decide posture. A service failure alone does not decide posture. Their combination changes the decision.”

### 5:15 — Evidence drill-down

> For the top three Protect accounts, show the evidence chain in a compact table: account, recommendation, sales signal, CX signal, verified delivery event, pricing signal, and source status. If evidence is missing or only synthetic, say so rather than filling the gap.

Open one citation only. Emphasize facts versus inference.

### 6:30 — Create the document

> Create a one-page document titled “NY/NJ Pricing Protection Brief.” Include the pricing objective from the cited Drive file, the Protect versus Can Raise summary, the top three Protect accounts with their evidence, recommended next actions, and a footer labeling synthetic and illustrative inputs. Keep it executive-ready and do not send it.

Show title, table, Drive citation, and assumptions footer.

### 7:45 — Schedule the task

> Create a scheduled task for every Monday at 8:00 AM Eastern named “NY/NJ Pricing Protection Brief.” Refresh this analysis using the latest governed data and the same cited Drive policy, update the document, and notify me with the link. Do not send it to any other recipient.

Show schedule, timezone, inputs, and sole recipient.

## Close

> “Context through one MCP. A decision across four governed domains. Evidence you can inspect. A document people can use. A scheduled task that keeps it current.”

## Guardrails

- Cross-domain questions route to the Retention Agent over pre-joined `mv_retention`; do not claim live joins across Agents.
- Drive supplies policy context; it is not ingested analytical data.
- Blocker and CX signals are real. Delivery, fees, contribution, and economics include labeled synthetic/illustrative inputs.
- The churn tier is rule-based, not a predictive model.
- Create documents/tasks from Genie One, not inside a curated Agent page.
- Never cut the hero question. At 7:30, switch to pre-created document/task fallbacks.

## Pre-flight

- Confirm the Google Doc **Superior Plus 2026 Pricing Plan (DEMO)** is in the connected Drive (https://docs.google.com/document/d/1FUk24Sb55As4WUOy9fe-cWFY_4noiwBGyRXZ9beISGs/edit).
- Authorize Drive MCP; warm the warehouse.
- Confirm Documents and Scheduled tasks are enabled.
- Pin four fallbacks: Drive excerpt, hero result, finished brief, task confirmation.

## Workspace instructions

- Upload [`genie_workspace_instructions.md`](genie_workspace_instructions.md) to the workspace.
- Instructions reduce repeated setup, routing ambiguity, and unnecessary agent fan-out.
- They intentionally omit Protect rules, thresholds, counts, account lists, and policy text; retrieve or reason over those fresh.
