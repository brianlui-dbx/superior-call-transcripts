-- =============================================================================
-- [GENIE ONE EXTENSION — ADDITIVE ONLY] mv_retention  (governed Metric View)
-- -----------------------------------------------------------------------------
-- The strategic-hub KPI layer for retention-aware pricing. Sourced from the
-- multi-fact base view account_retention_base (metric-views "one-fact-source"
-- rule: multi-fact KPIs go through a base view first). Deployed via a
-- bundle-managed SQL job (DABs has no native metric-view resource) — see
-- resources/genie_one_metric_views.job.yml.
--
-- Requires DBR 17.3+ for synonyms / display_name / format metadata.
-- Deterministic scenario constants are illustrative (labeled), not booked EBITDA:
--   $600 contribution per retained account, $150,000 program cost, 100,000-acct base.
-- =============================================================================
-- Session catalog/schema come from the job's :catalog/:schema parameters
-- (IDENTIFIER binds the value safely). This keeps the file additive and
-- portable across workspaces without ${...} text substitution.
USE CATALOG IDENTIFIER(:catalog);
USE SCHEMA IDENTIFIER(:schema);
CREATE OR REPLACE VIEW mv_retention
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
source: account_retention_base
comment: "Retention & pricing decision metrics: raise-vs-protect segmentation, churn-risk tiers, contribution and dollars at stake, and the illustrative churn-reduction economics. One row per opportunity."
dimensions:
  - name: Region
    expr: region
    synonyms: ["state", "market", "territory"]
  - name: Salesforce Stage
    expr: stage_name
    synonyms: ["stage", "deal stage", "pipeline stage"]
  - name: Churn Risk Tier
    expr: churn_risk_tier
    synonyms: ["risk tier", "risk level", "churn risk"]
  - name: Segment
    expr: raise_vs_protect_segment
    comment: "Strategic pricing call: 'Protect' = do not raise (service/price wound); 'Can Raise' = resilient."
    synonyms: ["raise or protect", "pricing segment", "raise vs protect"]
  - name: Primary Blocker
    expr: primary_blocker_code_name
    synonyms: ["blocker", "top blocker", "blocker code"]
  - name: Current Supplier
    expr: latest_current_supplier
    synonyms: ["competitor", "incumbent supplier"]
measures:
  # --- atomic measures ---
  - name: Opportunities
    expr: COUNT(1)
    synonyms: ["accounts", "opps", "opportunity count"]
  - name: At-Risk Opportunities
    expr: COUNT(1) FILTER (WHERE churn_risk_tier = 'High')
    comment: "Opportunities in the High churn-risk tier (rate objection AND a verified service failure)."
    synonyms: ["high risk accounts", "churn bomb accounts"]
  - name: Rate Objection And Failure
    expr: COUNT(1) FILTER (WHERE rate_uncompetitive_flag = 1 AND verified_failure_count > 0)
    comment: "The 'aha' cohort: rate-uncompetitive (4A rate objection and/or quoting above market) stacked on a verified runout/late delivery."
  - name: Total Contribution
    expr: SUM(trailing_contribution)
    format: {type: currency, currency_code: USD, decimal_places: {type: max, places: 0}}
    synonyms: ["contribution", "gross margin"]
  - name: Contribution At Risk
    expr: SUM(trailing_contribution) FILTER (WHERE raise_vs_protect_segment = 'Protect')
    comment: "Annual contribution tied to Protect-segment accounts — the dollars a mis-timed price increase puts at risk."
    format: {type: currency, currency_code: USD, decimal_places: {type: max, places: 0}}
    synonyms: ["margin at risk", "dollars at stake"]
  - name: Avg Rate Gap
    expr: AVG(rate_gap_vs_competitor)
    comment: "Average quoted rate above the competitor/current-supplier rate (from ai_extract)."
    format: {type: number, decimal_places: {type: exact, places: 3}}
  - name: Avg Hold Seconds
    expr: AVG(avg_hold_seconds)
    format: {type: number, decimal_places: {type: exact, places: 1}}
  - name: Avg Fee Load
    expr: AVG(fee_load)
    comment: "Average synthetic monthly ancillary fee load (rental/MUC/delivery) per account, in USD. Labeled synthetic."
    format: {type: currency, currency_code: USD, decimal_places: {type: exact, places: 2}}
    synonyms: ["fee load", "ancillary fees", "monthly fees", "fee burden"]
  # --- composed ratios (re-aggregate safely at any grain) ---
  - name: At-Risk Rate
    expr: "MEASURE(`At-Risk Opportunities`) / MEASURE(`Opportunities`)"
    format: {type: percentage, decimal_places: {type: exact, places: 1}}
    synonyms: ["percent at risk", "high risk share"]
  - name: Protect Share
    expr: "COUNT(1) FILTER (WHERE raise_vs_protect_segment = 'Protect') * 1.0 / COUNT(1)"
    format: {type: percentage, decimal_places: {type: exact, places: 1}}
  # --- illustrative churn-reduction economics (labeled scenario) ---
  # Net contribution = (accounts_saved * $600) - $150,000 program cost, scaled to a
  # 100,000-account base. Expressed per point of avoidable churn reduction so Genie
  # can answer 0.5 / 1 / 2 point scenarios by multiplying.
  - name: Net Contribution Per Churn Point
    expr: "(100000 * 0.01 * 600) - 150000"
    comment: "Illustrative: net annual contribution per 1.0 point of avoidable churn reduction on a 100k-account base ($600/acct, $150k program). NOT booked EBITDA."
    format: {type: currency, currency_code: USD, decimal_places: {type: max, places: 0}}
    synonyms: ["value per churn point", "net contribution per point"]
$$
