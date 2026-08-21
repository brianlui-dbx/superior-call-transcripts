-- ============ [CORE-validation — not a deliverable sheet] ============
-- WHAT THIS STEP DOES
--   Enforces a business rule from the rubric: every opportunity that HAS a real
--   blocker (disposition hard_blocker or friction) should have exactly ONE finding
--   flagged Primary = 'Yes' (the single main reason). This is a cross-row rule, so it
--   can't be a simple per-row check — we aggregate per opportunity, then assert.
--   Violations are reported as a warning (they don't stop the run).
CREATE OR REFRESH MATERIALIZED VIEW gold_primary_check (
  CONSTRAINT one_primary_per_blocker_opp EXPECT (primary_yes = expected_primary)
)
COMMENT 'Per-opportunity check: exactly one Primary=Yes when the opportunity has a blocker.'
AS
SELECT
  `Opp ID`                                                             AS opportunity_id,
  sum(CASE WHEN Primary = 'Yes' THEN 1 ELSE 0 END)                     AS primary_yes,
  -- 1 if this opportunity has at least one real blocker, else 0.
  CASE WHEN max(CASE WHEN Disposition IN ('hard_blocker','friction') THEN 1 ELSE 0 END) = 1
       THEN 1 ELSE 0 END                                              AS expected_primary
FROM gold_offer_blocker_findings
GROUP BY `Opp ID`;
