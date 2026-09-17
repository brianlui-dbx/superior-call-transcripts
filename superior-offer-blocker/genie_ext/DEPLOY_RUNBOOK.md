# Genie One Extension — Deploy & Validate Runbook

Additive deployment of the multi-domain Genie One extension. **Nothing existing is
modified.** Choose the CLI profile explicitly; never rely on implicit selection.

```bash
cd superior-offer-blocker
PROFILE=dbw-brlui-stable
CATALOG=dbw_brlui_stable
SCHEMA=call_transcripts_poc
WAREHOUSE_ID=50ad3a9993503e5b
```

## Pre-flight (static — already verified in this repo)
- [x] All new `resources/genie_one*.yml` parse; no duplicate resource keys vs the existing bundle.
- [x] Every notebook/SQL/JSON path referenced by the new resources exists.
- [x] Bundle vars used (`catalog`, `schema`, `warehouse_id`, `region_1`, `region_2`) all exist in `databricks.yml`.
- [x] All four Agent JSONs: valid `serialized_space` v2, ids 32-hex + sorted + unique, text instructions < 2000 chars, agent-mode benchmarks carry `evaluation_note`.
- [x] Base view column cross-check passes; four metric-view YAML bodies parse.
- [x] `create_agents_cli.sh` passes `bash -n`; `${catalog}/${schema}` remap verified.

## Step 1 — Validate the bundle (must be clean before deploy)
```bash
databricks bundle validate --strict --target dev --profile "$PROFILE"
```
Expect: lists existing resources (offer_blocker_pipeline, setup_job, dashboard) **plus** the new
`genie_one_ext_pipeline`, `genie_one_setup_ext_job`, `genie_one_metric_views_job`,
`genie_one_setup_job`. Zero errors.

| If validate errors | Likely cause / fix |
|---|---|
| `unknown field agent_json/description` | Older CLI rejecting extra notebook base_parameters — they are strings, allowed; upgrade CLI if flagged. |
| path not found under `pipeline_ext/` | Deploying from the wrong dir — run from `superior-offer-blocker/`. |
| DBR / metric view version | `synonyms/format` need **DBR 17.3+**; SQL warehouse must be on a 17.3+ channel. |

## Step 2 — Deploy (additive; existing state untouched)
```bash
databricks bundle deploy --target dev --profile "$PROFILE"
```

## Step 3 — Run in dependency order
```bash
# a) seed synthetic delivery (needs existing dim_salesforce_opportunity from the original setup_job)
databricks bundle run genie_one_setup_ext_job    --target dev --profile "$PROFILE"
# b) build ext_* facts + account_retention_base
databricks bundle run genie_one_ext_pipeline     --target dev --profile "$PROFILE"
# c) create the 4 governed metric views (mv_retention runs last; depends on the other 3)
databricks bundle run genie_one_metric_views_job --target dev --profile "$PROFILE"
# d) provision the 4 Genie Agents (uses the additive src/setup_ext/genie_setup_ext.py)
databricks bundle run genie_one_setup_job        --target dev --profile "$PROFILE"
```

### Alternative for step (d): CLI fallback
If you prefer not to run the agents job (e.g. quick re-provision during rehearsal):
```bash
PROFILE="$PROFILE" CATALOG="$CATALOG" SCHEMA="$SCHEMA" WAREHOUSE_ID="$WAREHOUSE_ID" \
  ./genie_ext/create_agents_cli.sh
```

## Step 4 — Validate the objects (read-only)
```bash
# metric views exist
databricks api get "/api/2.0/sql/statements" >/dev/null 2>&1 || true
for MV in mv_cx_service mv_pricing mv_delivery mv_retention; do
  databricks experimental aitools tools query --warehouse "$WAREHOUSE_ID" \
    "SELECT COUNT(*) FROM ${CATALOG}.${SCHEMA}.${MV}" --profile "$PROFILE"
done
# base view + facts populated
databricks experimental aitools tools query --warehouse "$WAREHOUSE_ID" \
  "SELECT churn_risk_tier, COUNT(*) FROM ${CATALOG}.${SCHEMA}.account_retention_base GROUP BY 1" --profile "$PROFILE"
# five Agents present
databricks genie list-spaces --profile "$PROFILE" | grep -E "Offer Blocker|CX & Service|Delivery Reliability|Pricing Position|Customer Retention"
```

## Step 5 — Rehearse the 7 demo questions via Genie One (routing check)
```bash
databricks genie ask -s demo "Which offer blockers drive the most Closed Lost value in NY and NJ, and how does 4A rank?" --profile "$PROFILE"
databricks genie ask -s demo "Average hold time and abandon rate by team in NY and NJ" --profile "$PROFILE"
databricks genie ask -s demo "NY and NJ opportunities with a rate objection and a verified runout or late delivery, ranked by contribution, with churn-risk tier" --profile "$PROFILE"
databricks genie ask -s demo "For those at-risk accounts, how far above competitor rate are we quoting, and what is the fee load?" --profile "$PROFILE"
databricks genie ask -s demo "Split my NY and NJ book into Can Raise vs Protect and show contribution at risk" --profile "$PROFILE"
databricks genie ask -s demo "Net annual contribution at 0.5, 1, and 2 points of churn reduction" --profile "$PROFILE"
```
For each, confirm Genie One routed to the intended Agent (per the talk-track cheat-sheet) and
pin the exact wording that routes correctly. Capture a labeled fallback screenshot per query.

## Rollback (fully additive — safe)
The extension creates only new objects. To remove: `databricks bundle destroy` removes the new
resources; drop the new tables/metric views (`ext_*`, `account_retention_base`, `mv_*`,
`ext_delivery_order_seed`) and trash the four Agents (`databricks genie trash-space <id>`).
The existing Offer Blocker pipeline, tables, dashboard, and Agent are never touched.
```
