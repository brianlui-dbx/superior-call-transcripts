-- [GENIE ONE EXTENSION — ADDITIVE] mv_cx_service (governed Metric View)
-- Single-fact source (ext_cx_contact) per the one-fact-source rule. Requires DBR 17.3+
-- for synonyms/format metadata.
CREATE OR REPLACE VIEW ${catalog}.${schema}.mv_cx_service
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
source: ${catalog}.${schema}.ext_cx_contact
comment: "Contact-center service experience: hold time, queue, abandon, repeat contacts, CSAT — by region/team/skill. One row per call."
dimensions:
  - name: Region
    expr: region
    synonyms: ["state", "market"]
  - name: Team
    expr: team_name
    synonyms: ["group", "queue team"]
  - name: Skill
    expr: skill_name
  - name: Match Status
    expr: match_status
    comment: "matched = call tied to a Salesforce opportunity; unmatched = service/other call with no opp."
measures:
  - name: Contacts
    expr: COUNT(1)
    synonyms: ["calls", "interactions"]
  - name: Avg Hold Seconds
    expr: AVG(hold_seconds)
    format: {type: number, decimal_places: {type: exact, places: 1}}
    synonyms: ["hold time", "average hold"]
  - name: Avg Queue Seconds
    expr: AVG(in_queue_seconds)
    format: {type: number, decimal_places: {type: exact, places: 1}}
  - name: Abandon Rate
    expr: AVG(abandon_flag)
    format: {type: percentage, decimal_places: {type: exact, places: 1}}
    synonyms: ["abandonment rate"]
  - name: Avg CSAT Index
    expr: AVG(csat_index)
    format: {type: number, decimal_places: {type: exact, places: 3}}
    synonyms: ["csat", "satisfaction"]
$$
