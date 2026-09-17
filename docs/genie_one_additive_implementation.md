# Genie One — Additive Implementation Plan
**Customer:** Superior Plus Propane · **Anchor:** Retention-aware pricing (Customer Growth ~$30M) · **Orchestration:** Native Genie One over curated Genie Agents

> **Aligned to the official [databricks/databricks-agent-skills](https://github.com/databricks/databricks-agent-skills).** Skills applied: `databricks-genie-agents` (curated Agents), `databricks-data-discovery` (Genie One routing), `databricks-metric-views` (governed KPIs), `databricks-dabs` + SDP-pipelines (bundle), `databricks-synthetic-data-gen` (story-driven Faker data).

## Terminology (per the skills — use it precisely)
- **Genie Agent** = a curated, per-domain natural-language agent (formerly "Genie Space"), scoped to specific tables/metric views with its own description, sample questions, and instructions. We build **four new ones**.
- **Genie One** = the cross-data discovery/chat layer (`databricks-data-discovery`; backend `onechat`). It **routes a question to the most relevant Genie Agent based on that Agent's `description`**, then can search other assets. Native, no Supervisor Agent / Agent Bricks.
- **Design consequence:** multi-agent routing is *description-driven*. Each Agent's `description` (Design Priority #1) is the single most important field. Reliable cross-domain answers come from a **governed table/metric view that already pre-joins the domains**, exposed through one Agent — not from Genie live-joining four Agents.

## Guiding rule: **ADD objects only — never modify existing ones**
- ✅ Create new tables/metric views (new names), a new pipeline dir + resource, four new Genie Agents (new JSON), new job resources, and **read** from existing tables.
- ❌ Edit any existing `pipeline/transformations/**` SQL, alter/overwrite existing tables, edit `resources/*.yml` or `genie/genie_agent.json`, or touch the existing dashboard/Agent.
- **Spine:** reuse existing `opportunity_id` (+ `region`, `stage_name`). (Real `account_id` crosswalk = production upgrade, out of additive scope.)

---

## New objects (all net-new)

### A. New SDP pipeline (existing pipeline untouched)
New **`resources/genie_one.pipeline.yml`** → pipeline `genie_one_ext_poc`, `serverless: true`, `channel: CURRENT`, `development: true`, `root_path: ../pipeline_ext`, glob `../pipeline_ext/transformations/**`, same `catalog`/`schema` config vars (follows `databricks-dabs` SDP pattern). New SQL lives under a **new** `pipeline_ext/` tree so the existing pipeline's glob is unchanged.

New materialized views under `pipeline_ext/transformations/` — all **read** existing published tables, write **new** names:

| New table | Reads (read-only) | Purpose |
|---|---|---|
| `ext_cx_contact` | `bronze_transcripts` | **CX fact.** Surfaces already-ingested NICE CXone ops fields: `holdSeconds`, `inQueueSeconds`, `abandonSeconds`, `totalDurationSeconds`, `agentName`/`teamName`/`skillName`, `csatSentiment`+index, disposition, phone. One row per call. |
| `ext_pricing_position` | `gold_opportunity_enrichment` | **Pricing fact.** Promotes existing `ai_extract` quoted-vs-competitor rates; adds deterministic synthetic `list_rate`, `fee_load`. |
| `ext_delivery_order` | `dim_salesforce_opportunity` (key list) | **Delivery fact (synthetic, story-driven).** Per-opportunity delivery history w/ `runout_verified_flag`, `late_delivery_flag`. |
| `account_retention_base` | `gold_offer_blocker_summary`, `gold_call_enrichment_enh`, `ext_cx_contact`, `ext_pricing_position`, `ext_delivery_order`, `dim_salesforce_opportunity` | **Base view** (one fact = multiple facts combined) feeding the retention metric view. **Each source pre-aggregated to `opportunity_id` grain BEFORE joining** — no call×delivery×fee fan-out. |

### B. Governed Metric Views — *reusable KPIs go here, not SQL snippets* (`databricks-metric-views`)
The skill's hard rule: reusable business metrics belong in **governed Metric Views**, referenced via `MEASURE()`, so definitions are consistent and Genie reasons better. Commit each as `*.metric_view.sql` and deploy via a **bundle-managed SQL job** (DABs has no native metric-view resource):
- **`mv_cx_service`** (single fact `ext_cx_contact`, dims joined in-view): measures `avg_hold_seconds`, `abandon_rate`, `repeat_contact_rate`, `avg_csat_index`.
- **`mv_pricing`** (fact `ext_pricing_position`): `avg_rate_gap_vs_competitor`, `avg_fee_load`.
- **`mv_delivery`** (fact `ext_delivery_order`): `runout_rate`, `late_delivery_rate`, `verified_failure_count`.
- **`mv_retention`** (base view `account_retention_base` — multi-fact, so a base view is correct per the one-fact-source rule): `churn_risk_tier` (rule-based), `accounts_at_risk`, `trailing_contribution`, `contribution_at_risk`, `raise_vs_protect_segment`, plus the illustrative $/churn-point scenario measures. **This is the strategic hub.**

Each metric view carries agent metadata (`comment`, `synonyms`, `display_name`, `format`) so Genie answers cleanly (requires DBR 17.3+).

### C. Synthetic data — story-driven (`databricks-synthetic-data-gen`)
New notebook **`src/setup_ext/gen_ext_data.py`** using **Spark + Faker + pandas UDFs on serverless** (never uniform; skew/80-20; write master→read-back for FKs). **Story:** *a cluster of high-value NY/NJ accounts hit by verified runouts + late deliveries during the transformation also carry 4A rate objections and above-market rate gaps → they're the churn bomb; retaining ~2pts ≈ $1.05M contribution.* Writes only new tables; every row tagged `is_synthetic = true`. Catalog/schema come from bundle vars (never defaulted). Keyed to existing `opportunity_id`s.

### D. Four new Genie Agents (new JSON + new job; existing Agent untouched)
Built per `databricks-genie-agents` **Design Priorities** — description first, then metric-view semantics, focused sources (≤5 objects each), `column_configs` (descriptions/synonyms/format-assistance/entity-matching/hidden), join specs, then example SQL; **text instructions last** using the five canonical headers. Sources are the **metric views** (governed), not raw facts, unless raw detail is needed.

| Agent (title) | Sources | `description` (drives Genie One routing — disjoint vocabulary) |
|---|---|---|
| **CX & Service Recovery** | `mv_cx_service` | "Contact-center service experience: hold time, queue/abandon, repeat contacts, CSAT, agent/team." |
| **Delivery Reliability** | `mv_delivery` | "Propane delivery reliability: verified runouts, late/missed deliveries, gallons, capacity." |
| **Pricing Position** | `mv_pricing` | "Account price posture vs market: quoted vs competitor rate, rate gap, fee load." |
| **Customer Retention Decision** | `mv_retention` (+ raw `account_retention_base` only if raw-detail Qs needed) | "Retention & pricing decisions: raise-vs-protect segmentation, churn-risk tier, contribution and dollars at stake, intervention economics." **← strategic questions route here.** |

New **`resources/genie_one.job.yml`** → `genie_one_setup_job`, one task per Agent, each a `notebook_task` reusing the **existing** `src/setup/genie_setup.py` (title-idempotent; not edited) with a new `title`/`files_path`. Agents stored as `genie_ext/genie_{cx,delivery,pricing,retention}.json` (parsed objects per the CI/CD convention; stringified with `jq -c '.' | jq -Rs '.'` at create). Tag each Agent + underlying tables with a domain tag for discoverability. Net result: **five Agents** under Genie One (existing Offer Blocker + four new).

### E. New dashboard (optional, additive)
`src/dashboards/retention_pricing.lvdash.json` + `resources/retention_pricing.dashboard.yml` over `mv_retention`. Existing dashboard untouched.

---

## Phased delivery (additive, ~8–9 working days)

| Phase | Adds | Skill | Exit criterion |
|---|---|---|---|
| **0 — Capability check (0.5d)** | — | data-discovery | Genie One available (`databricks genie ask --help`); can create/share Agents; DBR 17.3+ for MV metadata; warehouse resolved (`aitools get-default-warehouse`). |
| **1 — CX facts + metric view + Agent (1.5d)** *real* | `ext_cx_contact`, `mv_cx_service`, CX Agent | pipelines, metric-views, genie-agents | CX Qs answer via `MEASURE()`; existing pipeline/Agent still green. |
| **2 — Delivery synthetic + MV + Agent (1.5d)** | `gen_ext_data.py`, `ext_delivery_order`, `mv_delivery`, Delivery Agent | synthetic-data-gen | Verified-runout story present, skewed; rows labeled `is_synthetic`. |
| **3 — Pricing MV + Agent (1d)** | `ext_pricing_position`, `mv_pricing`, Pricing Agent | metric-views | Rate-gap reconciles to existing `ai_extract`. |
| **4 — Retention base + MV + Agent (1.5d)** *core* | `account_retention_base`, `mv_retention`, Retention Agent, `genie_one.job.yml` | metric-views, genie-agents | Raise-vs-protect + $/churn-point answerable in ONE Agent; no fan-out. |
| **5 — Descriptions + routing + benchmarks (1.5d)** | tune each `description`; ~30 benchmark items (2–4 phrasings × core Qs) per `optimize-genie-agent`; validate via Conversation API | genie-agents | Genie One routes all 7 demo Qs to the right Agent; each cross-domain Q resolved inside Retention Agent. |
| **6 — Dashboard + rehearsal (1d)** | retention dashboard; frozen snapshot | aibi-dashboards | Clean 20-min run; labeled fallback per query. |

**Deploy (all additive):**
```
databricks bundle validate --strict -t dev -p <profile>
databricks bundle deploy -t dev -p <profile>
databricks bundle run deploy_metric_views_job -t dev -p <profile>   # applies *.metric_view.sql
databricks bundle run genie_one_ext_pipeline -t dev -p <profile>    # builds ext_* + base view
databricks bundle run genie_one_setup_job -t dev -p <profile>       # provisions 4 new Agents
```
Validate Agents read-only before proposing live: `databricks genie ask -s demo "..."`. Short on time → Phases 0–1 give a genuine **two-Agent** Genie One (Offer Blocker + CX), both real.

**Guardrails:** lost opportunity ≠ churn · transcript calls ≠ full contact population · verified runout needs an ops record · rule-based risk tiers only (no unvalidated probabilities) · every synthetic row labeled · demo scoped NY/NJ, USD, gallons · qualify every column in SQL snippets/joins · text instructions only for global behavior.
