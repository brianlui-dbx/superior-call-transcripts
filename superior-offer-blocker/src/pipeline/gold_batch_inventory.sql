-- ============ [CORE-validation — not a deliverable sheet] ============
-- WHAT THIS STEP DOES
--   Reproduces the original workflow's "inventory line" as a data check. The human
--   analyst was told to first count segments/opportunities and confirm the total
--   before analyzing. Here we compute those counts automatically (one row) so you
--   can eyeball that everything was processed. `segment` = one call; `opportunity`
--   = one deal; a finding row = one coded candidate issue.
CREATE OR REFRESH MATERIALIZED VIEW gold_batch_inventory
COMMENT 'Batch counts (segments, opportunities, finding rows) + the "Detected N segments across M opportunities." sentinel.'
AS
SELECT
  (SELECT count(*)                        FROM silver_transcript_sf_joined)   AS segment_count,
  (SELECT count(DISTINCT opportunity_id)  FROM silver_opportunity_dialogue)   AS opportunity_count,
  (SELECT count(*)                        FROM gold_offer_blocker_findings)   AS finding_rows,
  format_string(
    'Detected %d segments across %d opportunities.',
    (SELECT count(*)                       FROM silver_transcript_sf_joined),
    (SELECT count(DISTINCT opportunity_id) FROM silver_opportunity_dialogue)
  ) AS inventory_line;
