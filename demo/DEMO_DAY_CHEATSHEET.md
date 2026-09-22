# Demo Day Cheat Sheet — Genie One in 10 Minutes

**Anchor:** Capture pricing upside without buying it back in attrition.

**Banner:** Illustrative · NY/NJ · USD/gallons · synthetic rows labeled.

## Five prompts, typed verbatim

### 0:40 — Question 1: offer-blocker intelligence

> Across NY and NJ Closed Lost opportunities, what are the leading offer blockers? Separate hard blockers and friction from issues that were merely mentioned or resolved, and include one supporting customer quote for the leading true blocker.

Show the ranked blockers, disposition split, and one quote. Keep this strictly single-domain.

### 1:50 — Question 2: cross-domain hero + Google Drive MCP

> Use Google Drive to retrieve the “Superior Plus 2026 Pricing Plan (DEMO).” Based on that plan, which NY and NJ accounts should be exempted from or receive a reduced next price increase, and which can absorb the full increase? Rank the accounts needing protection by contribution at risk, and justify the decision with sales, CX, delivery, and pricing evidence. Cite the plan and label inferred or synthetic inputs.

Expected anchors: **225 Protect / 66 Can Raise · 76 objection + service-failure accounts · ~$0.16 rate gap · ~$22 fee load · ~$134K contribution at risk.**

Say: “A price objection alone does not decide posture. A service failure alone does not decide posture. Their combination changes the decision.”

### 5:20 — Evidence drill-down

> For the top three accounts recommended for an exemption or reduced increase, show the evidence chain in a compact table: account, recommended pricing action, sales signal, CX signal, verified delivery event, pricing signal, and source status. If evidence is missing or synthetic, say so rather than filling the gap.

Open one citation only. Emphasize facts versus inference.

### 6:20 — Create the document

> Create a one-page document titled “NY/NJ Price Increase Decision Brief.” Include the pricing objective from the cited Drive file, the account breakdown for exemption or reduced increase versus full increase, the top three accounts needing an exception with their evidence, recommended next actions, and a footer labeling synthetic and illustrative inputs. Keep it executive-ready and do not send it.

Show title, table, Drive citation, and assumptions footer.

### 7:35 — Schedule the task

> Create a scheduled task for every Monday at 8:00 AM Eastern named “NY/NJ Price Increase Decision Brief.” Using the latest governed data and the current cited Drive policy, refresh which accounts warrant an exemption or reduced increase versus the full increase, update the document, and notify only me with the link.

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
- Pin four fallbacks: blocker result, hero result with Drive citation, finished brief, task confirmation.

## Workspace instructions

- Upload [`genie_workspace_instructions.md`](genie_workspace_instructions.md) to the workspace.
- Instructions reduce repeated setup, routing ambiguity, and unnecessary agent fan-out.
- They intentionally omit Protect rules, thresholds, counts, account lists, and policy text; retrieve or reason over those fresh.
