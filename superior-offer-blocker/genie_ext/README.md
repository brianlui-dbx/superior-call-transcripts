# Genie One Extension — additive artifacts

Adds a multi-domain **Genie One** experience on top of the existing Offer Blocker
solution **without modifying any existing pipeline, table, job, dashboard, or the
existing Genie Agent**. Built to the conventions in
[databricks/databricks-agent-skills](https://github.com/databricks/databricks-agent-skills)
(`databricks-genie-agents`, `databricks-data-discovery`, `databricks-metric-views`,
`databricks-dabs`, `databricks-synthetic-data-gen`).

## What's here (all net-new)
| File | Role |
|---|---|
| `../pipeline_ext/transformations/gold/account_retention_base.sql` | Multi-fact **base view** (one row per `opportunity_id`), each source pre-aggregated **before** joining (anti-fan-out). Reads existing tables + `ext_*` facts. |
| `../src/metric_views/mv_retention.metric_view.sql` | Governed **Metric View** (the strategic hub). Composed `MEASURE()` ratios, agent metadata, labeled churn-reduction economics. |
| `build_genie_retention.py` → `genie_retention.json` | **Customer Retention Decision** Genie Agent (`serialized_space` v2): metric-view source, `MEASURE()` example SQL, 5-header text instructions, 4 benchmarks. Genie One routes strategic questions here by the Agent `description`. |
| `../resources/genie_one.pipeline.yml` | New SDP pipeline (separate `root_path`/glob). |
| `../resources/genie_one_metric_views.job.yml` | Bundle-managed SQL job to deploy the metric view(s). |
| `../resources/genie_one.job.yml` | Job to provision the new Agent(s), reusing the existing `genie_setup.py`. |

## Now complete (all additive)
**Facts:** `ext_cx_contact.sql` (real CXone ops, non-sales calls preserved via LEFT JOIN),
`ext_pricing_position.sql` (real ai_extract rates + synthetic list_rate/fee_load),
`ext_delivery_order.sql` (reads the synthetic seed). **Base view:** `account_retention_base.sql`.
**Generator:** `src/setup_ext/gen_ext_data.py` (Spark+Faker, skewed/story-driven, `is_synthetic`) → `ext_delivery_order_seed`.
**Metric views:** `mv_cx_service`, `mv_pricing`, `mv_delivery`, `mv_retention` (hub).

**Agents (all four complete):** `genie_cx.json`, `genie_delivery.json`, `genie_pricing.json`,
`genie_retention.json` — built by their `build_genie_*.py` scripts and provisioned by the
additive `src/setup_ext/genie_setup_ext.py` (the existing `genie_setup.py` reads a fixed
path and is not modified). With the existing Offer Blocker Agent that is **five Agents**
under Genie One. Routing is driven by each Agent's `description` (set in `genie_one.job.yml`).

## Nothing left to author
The extension is feature-complete: facts → base view → four metric views → four Agents,
plus all DAB resources. Regenerate any Agent JSON deterministically with its build script.

## Deploy (additive; existing bundle unaffected)
```bash
PROFILE=<your-profile>
databricks bundle validate --strict -t dev -p "$PROFILE"
databricks bundle deploy   -t dev -p "$PROFILE"

# 1) seed the synthetic delivery table (needs existing dim_salesforce_opportunity)
databricks bundle run genie_one_setup_ext_job    -t dev -p "$PROFILE"
# 2) build ext_* facts + base view
databricks bundle run genie_one_ext_pipeline     -t dev -p "$PROFILE"
# 3) create governed metric views (mv_retention runs last; it depends on the others)
databricks bundle run genie_one_metric_views_job -t dev -p "$PROFILE"
# 4) provision the new Genie Agent(s)
databricks bundle run genie_one_setup_job        -t dev -p "$PROFILE"

# validate the Agent read-only before demo (Genie One CLI)
databricks genie ask -s demo "Split my NY and NJ book into Can Raise vs Protect and show contribution at risk"
```

## Notes
- `genie_retention.json` carries `${catalog}.${schema}` placeholders; remap to the
  real catalog/schema before `create-space` (a single string replace over the file,
  per the CI/CD skill). Then stringify with `jq -c '.' | jq -Rs '.'` when passing to
  `databricks genie create-space`/`update-space`.
- Regenerate the Agent JSON deterministically with `python3 build_genie_retention.py > genie_retention.json`.
- Metric-view semantic metadata (`synonyms`/`display_name`/`format`) requires **DBR 17.3+**.
