-- ============ [CORE-validation — not a deliverable sheet] ============
-- WHAT THIS STEP DOES
--   A "sidecar" table collecting any findings that had an AI error or an
--   out-of-expected-range code/disposition. In a batch job we don't want one bad
--   row to fail the run, so we keep everything in the main table and simply mirror
--   the suspect rows here for a human to inspect. Normally this table is empty.
CREATE OR REFRESH MATERIALIZED VIEW gold_findings_quarantine
COMMENT 'Suspect findings (AI error or out-of-domain code/disposition) for inspection. Usually empty.'
-- Inherits the spaced headers from gold_offer_blocker_findings, so it needs column mapping too.
TBLPROPERTIES ('delta.columnMapping.mode' = 'name')
AS
SELECT *
FROM gold_offer_blocker_findings
WHERE ai_error IS NOT NULL
   OR Code NOT IN ('4A','4B','4C','4D','4E','4F','—')
   OR Disposition NOT IN ('hard_blocker','friction','mention_only','resolved','latent','insufficient_evidence','—');
