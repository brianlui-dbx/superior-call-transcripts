-- [GENIE ONE EXTENSION — ADDITIVE] mv_pricing (governed Metric View)
-- Single-fact source (ext_pricing_position). Requires DBR 17.3+ for metadata.
CREATE OR REPLACE VIEW ${catalog}.${schema}.mv_pricing
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
source: ${catalog}.${schema}.ext_pricing_position
comment: "Account price posture vs market: quoted vs competitor rate, rate gap, fee load. One row per opportunity."
dimensions:
  - name: Salesforce Stage
    expr: stage_name
    synonyms: ["stage", "deal stage"]
measures:
  - name: Opportunities
    expr: COUNT(1)
  - name: Avg Quoted Rate
    expr: AVG(quoted_rate)
    format: {type: number, decimal_places: {type: exact, places: 4}}
    synonyms: ["our rate", "quoted rate"]
  - name: Avg Competitor Rate
    expr: AVG(competitor_rate)
    format: {type: number, decimal_places: {type: exact, places: 4}}
    synonyms: ["market rate", "competitor rate"]
  - name: Avg Rate Gap
    expr: AVG(rate_gap_vs_competitor)
    comment: "Positive => Superior quoting above the competitor/current-supplier rate."
    format: {type: number, decimal_places: {type: exact, places: 4}}
    synonyms: ["rate gap", "price gap vs market"]
  - name: Avg Fee Load
    expr: AVG(fee_load)
    format: {type: currency, currency_code: USD, decimal_places: {type: exact, places: 2}}
    synonyms: ["fees", "fee load"]
$$
