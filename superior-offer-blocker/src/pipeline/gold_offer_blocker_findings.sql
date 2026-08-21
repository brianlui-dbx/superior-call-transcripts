-- ============ [CORE — like-for-like: this IS the Excel "AI Output" sheet, as Delta] ============
-- WHAT THIS STEP DOES
--   Parses the ai_query JSON, explodes it to one row per finding, and shapes the
--   columns to match the manual workflow's "AI Output" spreadsheet exactly. This is
--   THE deliverable table. (The Pivot Summary and Backup sheets are intentionally
--   not reproduced.)
--
-- COLUMN MEANINGS (one row = one evaluated candidate issue for an opportunity)
--   Version/Batch      : which prompt revision + transcript batch produced this (metadata).
--   Opp ID             : the Salesforce Opportunity ID (taken from our data, exact).
--   Salesforce Stage   : the deal's stage (Open / Closed Won / Closed Lost).
--   Rate               : the quoted per-unit price tied to the issue (e.g. "2.04/gal").
--   Code / Code Name   : the blocker code 4A-4F (or "—" for none) and its display name.
--   Primary            : "Yes" if this is the main blocker for the opportunity, else "—".
--   Qualifier          : sub-reason within the code (e.g. "current-supplier").
--   Disposition        : hard_blocker | friction | mention_only | resolved | latent |
--                        insufficient_evidence | — (how much it actually affected the deal).
--   Confidence         : High | Medium | Low (evidence strength).
--   Evidence           : one-sentence justification quoting/citing the transcript.
--
-- EXPECTATIONS (data-quality "warn" checks; rows are kept, violations reported)
--   Bad rows are also routed to gold_findings_quarantine (see that file) for inspection.

CREATE OR REFRESH MATERIALIZED VIEW gold_offer_blocker_findings (
  CONSTRAINT valid_code            EXPECT (Code IN ('4A','4B','4C','4D','4E','4F','—')),
  CONSTRAINT valid_disposition     EXPECT (Disposition IN ('hard_blocker','friction','mention_only','resolved','latent','insufficient_evidence','—')),
  CONSTRAINT no_ai_error           EXPECT (ai_error IS NULL),
  -- Cross-check: the generator's code should be one the classifier also flagged
  -- (or "—"). Divergence is surfaced as a warning, not a failure.
  CONSTRAINT code_matches_classifier EXPECT (Code = '—' OR candidate_codes IS NULL OR array_contains(candidate_codes, Code))
)
COMMENT 'THE deliverable: one row per offer-blocker finding (mirrors the Excel "AI Output" sheet).'
-- Column mapping lets us keep the exact spreadsheet headers ("Opp ID", "Salesforce Stage",
-- "Code Name") which contain spaces (Delta forbids those without it).
TBLPROPERTIES ('delta.columnMapping.mode' = 'name')
AS
WITH parsed AS (
  SELECT
    opportunity_id,
    stage_name,
    candidate_codes,
    quoted_rate,
    ai_response.errorMessage AS ai_error,
    -- Turn the JSON string into a typed struct we can explode.
    -- NOTE: with failOnError => false, ai_query returns STRUCT{result, errorMessage}
    -- (the payload is in `result`).
    from_json(
      ai_response.result,
      'STRUCT<findings: ARRAY<STRUCT<opp_id:STRING,rate:STRING,code:STRING,primary:BOOLEAN,qualifier:STRING,disposition:STRING,confidence:STRING,evidence:STRING>>>'
    ) AS parsed
  FROM gold_findings_raw
),
exploded AS (
  -- explode_outer keeps opportunities that produced zero findings (or errored),
  -- so no opportunity silently disappears from the output.
  SELECT opportunity_id, stage_name, candidate_codes, quoted_rate, ai_error,
         explode_outer(parsed.findings) AS f
  FROM parsed
)
SELECT
  '${prompt_version}'                                   AS Version,
  '${batch_label}'                                      AS Batch,
  e.opportunity_id                                      AS `Opp ID`,
  e.stage_name                                          AS `Salesforce Stage`,
  -- Prefer the rate ai_extract found; fall back to the rate in the finding; else "—".
  coalesce(nullif(trim(e.quoted_rate), ''), nullif(trim(e.f.rate), ''), '—') AS Rate,
  coalesce(e.f.code, '—')                               AS Code,
  cc.description                                        AS `Code Name`,   -- display name from the catalog dim
  CASE WHEN e.f.primary THEN 'Yes' ELSE '—' END         AS Primary,
  coalesce(nullif(trim(e.f.qualifier), ''), '—')        AS Qualifier,
  coalesce(e.f.disposition, '—')                        AS Disposition,
  coalesce(e.f.confidence, '—')                         AS Confidence,
  coalesce(nullif(trim(e.f.evidence), ''), '—')         AS Evidence,
  coalesce(e.f.code, '—')                               AS Key,
  -- helper/validation columns (not in the original sheet, handy for trust):
  e.candidate_codes                                     AS candidate_codes,
  e.ai_error                                            AS ai_error
FROM exploded e
LEFT JOIN ${catalog}.${schema}.dim_code_categories cc
  ON e.f.code = cc.code;
