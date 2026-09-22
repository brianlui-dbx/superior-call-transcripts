# Genie One Demo for Superior Plus Propane — Package Index

**One front door for the whole package.** This extends the existing `superior-offer-blocker`
solution into a **multi-domain, native Genie One** demo anchored on a strategic outcome:
**retention-aware pricing — capture the pricing upside without buying it back in attrition**
(Superior Delivers → Customer Growth pillar, ~$30M).

> **Two hard constraints honored throughout:** (1) **Native Genie One only** — no Supervisor
> Agent / Agent Bricks; cross-domain synthesis is pre-joined in a governed metric view.
> (2) **Additive only** — every artifact is net-new; **zero existing files modified**.
> Built to the conventions in [databricks/databricks-agent-skills](https://github.com/databricks/databricks-agent-skills).

---

## Start here (by role)

| You are… | Read, in order |
|---|---|
| **Exec / reviewer** (5 min) | [One-pager](genie_one_demo_onepager.html) → this index's *Solution at a glance* |
| **Presenter** (demo day) | [10-minute talk track](../demo/genie_one_demo_talktrack.md) → [10-minute demo-day cheat-sheet](../demo/DEMO_DAY_CHEATSHEET.md) |
| **SA / builder** | [Implementation plan](genie_one_additive_implementation.md) → [Build tasks](genie_one_demo_build_tasks.md) → [genie_ext/README](../superior-offer-blocker/genie_ext/README.md) → [Deploy runbook](../superior-offer-blocker/genie_ext/DEPLOY_RUNBOOK.md) |

---

## Solution at a glance
- **5 Genie Agents under native Genie One:** Offer Blocker *(existing)* + **CX & Service Recovery**, **Delivery Reliability**, **Pricing Position**, **Customer Retention Decision** *(new)*.
- **Routing:** Genie One picks the Agent by its `description`. Every cross-domain/strategic question is engineered to land on the **Retention Decision** Agent, whose governed `mv_retention` metric view **pre-joins the domains** (native-only reliability tactic — no live 4-way join).
- **The "aha":** a rate objection (4A) **stacked on** a verified runout/late delivery = the churn bomb. No single system sees it; the pre-joined metric view does.
- **The economics (illustrative, labeled):** 100K accts · $600/acct · $150K cost → **$1.05M net @ 2pt** churn reduction, break-even **0.25pt**.

---

## Document map

### Strategy & narrative — `docs/`
| File | What it is |
|---|---|
| [genie_one_demo_onepager.html](genie_one_demo_onepager.html) / [.md](genie_one_demo_onepager.md) | Slide-ready one-pager (open HTML → print landscape → PDF). |
| [genie_one_demo_talktrack.md](../demo/genie_one_demo_talktrack.md) | Minute-by-minute 10-min flow: single-domain blocker intelligence, cross-domain reasoning with Drive context, document creation, and scheduled task. |
| [genie_workspace_instructions.md](../demo/genie_workspace_instructions.md) | Uploadable workspace instructions with direct routing, freshness, response, and action guardrails. |
| [Superior_Plus_2026_Pricing_Plan_DEMO.md](../demo/Superior_Plus_2026_Pricing_Plan_DEMO.md) | Repo source for the synthetic pricing plan. Published as the Google Doc **Superior Plus 2026 Pricing Plan (DEMO)** ([link](https://docs.google.com/document/d/1FUk24Sb55As4WUOy9fe-cWFY_4noiwBGyRXZ9beISGs/edit)) for the Drive MCP retrieval beat. |
| [genie_one_additive_implementation.md](genie_one_additive_implementation.md) | Additive, skill-aligned implementation plan (terminology, domains, phases). |
| [genie_one_demo_build_tasks.md](genie_one_demo_build_tasks.md) | Phased build task list (earlier native-only version; superseded on specifics by the implementation plan). |

### Build artifacts — `superior-offer-blocker/`
| Path | What it is |
|---|---|
| `pipeline_ext/transformations/gold/ext_cx_contact.sql` | CX fact from bronze CXone ops (LEFT JOIN preserves non-sales calls). |
| `pipeline_ext/transformations/gold/ext_pricing_position.sql` | Pricing fact (real ai_extract rates + synthetic list_rate/fee_load). |
| `pipeline_ext/transformations/gold/ext_delivery_order.sql` | Delivery fact (reads the synthetic seed; verified-runout guardrail). |
| `pipeline_ext/transformations/gold/account_retention_base.sql` | Multi-fact **base view**, one row per opportunity, pre-aggregated (anti-fan-out). |
| `src/metric_views/mv_{cx_service,pricing,delivery,retention}.metric_view.sql` | 4 governed metric views; `mv_retention` is the strategic hub. |
| `src/setup_ext/gen_ext_data.py` | Spark+Faker synthetic delivery seed (skewed, story-driven, `is_synthetic`). |
| `src/setup_ext/genie_setup_ext.py` | Additive Agent-provisioning notebook (parameterized; existing one untouched). |
| `genie_ext/build_genie_*.py` → `genie_*.json` | 4 Agent build scripts + their validated `serialized_space` v2 JSONs. |
| `genie_ext/create_agents_cli.sh` | CLI fallback to provision the 4 Agents (with catalog remap). |

### DAB resources — `superior-offer-blocker/resources/`
`genie_one.pipeline.yml` (ext SDP) · `genie_one_setup_ext.job.yml` (seed) · `genie_one_metric_views.job.yml` (4 MV tasks) · `genie_one.job.yml` (4 Agent tasks).

### Operations — `superior-offer-blocker/genie_ext/`
[README](../superior-offer-blocker/genie_ext/README.md) (artifact overview) · [DEPLOY_RUNBOOK](../superior-offer-blocker/genie_ext/DEPLOY_RUNBOOK.md) (validate→deploy→run→rehearse→rollback) · [DEMO_DAY_CHEATSHEET](../superior-offer-blocker/genie_ext/DEMO_DAY_CHEATSHEET.html) (presenter card).

---

## Deploy in one glance (details in the runbook)
```bash
cd superior-offer-blocker
PROFILE=dbw-brlui-stable
databricks bundle validate --strict --target dev --profile "$PROFILE"
databricks bundle deploy               --target dev --profile "$PROFILE"
databricks bundle run genie_one_setup_ext_job    --target dev --profile "$PROFILE"  # seed synthetic delivery
databricks bundle run genie_one_ext_pipeline     --target dev --profile "$PROFILE"  # facts + base view
databricks bundle run genie_one_metric_views_job --target dev --profile "$PROFILE"  # 4 metric views
databricks bundle run genie_one_setup_job        --target dev --profile "$PROFILE"  # 4 Genie Agents
```
Prereq: the existing `setup_job` has already created `dim_salesforce_opportunity`. Metric-view
metadata needs **DBR 17.3+**. Validate live with `databricks genie ask`.

## Status & what's left to you
**Complete & validated (static):** all data objects, 4 Agents (structure-checked), DAB resources,
CLI fallback, and docs. **0 existing files modified.**
**Yours to run (needs the live workspace — no CLI/warehouse access from the authoring env):**
`bundle validate`, the four `bundle run`s, and rehearsing the 10-minute hero flow to pin routing and prepare fallbacks.

## Guardrails (carried across every artifact)
Lost opportunity ≠ churn · transcript calls ≠ full contact population · a verified runout needs an
operational record · rule-based risk tiers only (no unvalidated probabilities) · every synthetic
row labeled `is_synthetic` · demo scoped to NY/NJ, USD, gallons · economics are illustrative, not
booked EBITDA.
