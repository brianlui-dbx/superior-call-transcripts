-- ============ [CORE — like-for-like with original/offer_blocker.py (data prep)] ============
-- WHAT THIS STEP DOES
--   Turns raw calls into "calls that belong to a known sales opportunity in the
--   target regions." It reproduces the original Python prep, step for step:
--     1. Normalize the customer phone number to 10 digits.
--     2. Join to the (synthetic) Salesforce table on that phone to attach the
--        opportunity_id (the deal), its stage, region, and created date.
--     3. Number each call chronologically within its opportunity -> "Seg X of N".
--     4. Build `combined_key`, the human-readable traceability string the LLM sees.
--     5. Keep only calls in the two demo regions.
--
-- DOMAIN NOTES
--   opportunity  = one sales deal (Salesforce Opportunity ID).
--   segment      = one call. An opportunity can have several calls (segments).
--   "Seg X of N" = this call's chronological position among the opportunity's N calls.
--   This is a Materialized View (batch), not streaming, because the window functions
--   below need to see all of an opportunity's calls at once.

CREATE OR REFRESH MATERIALIZED VIEW silver_transcript_sf_joined
COMMENT 'Transcript calls joined to their Salesforce opportunity, numbered chronologically, filtered to the demo regions.'
AS
WITH normalized AS (
  SELECT
    *,
    -- Strip everything that is not a digit. If 11+ digits (e.g. leading US "1"),
    -- keep the last 10. This mirrors the original regexp_replace + last-10 rule.
    CASE
      WHEN length(regexp_replace(clientPhoneNumber, '[^0-9]', '')) >= 11
        THEN right(regexp_replace(clientPhoneNumber, '[^0-9]', ''), 10)
      ELSE regexp_replace(clientPhoneNumber, '[^0-9]', '')
    END AS phone10
  FROM bronze_transcripts
),
valid AS (
  -- Drop rows without a clean 10-digit phone (can't be joined to a customer).
  SELECT * FROM normalized WHERE length(phone10) = 10
)
SELECT
  t.id,
  t.phone10                       AS clientPhoneNumber,
  sf.opportunity_id,                          -- the deal this call belongs to
  sf.stage_name,                              -- Open / Closed Won / Closed Lost
  sf.region,
  sf.created_datetime,
  t.recordingStartTime,
  t.interactionDurationSeconds,
  t.interwovenTranscript,                     -- kept for dialogue assembly downstream
  -- N = how many calls this opportunity has (over the whole partition).
  count(*)     OVER (PARTITION BY t.phone10)                                  AS seg_count,
  -- X = this call's chronological position within the opportunity.
  row_number() OVER (PARTITION BY t.phone10 ORDER BY t.recordingStartTime)    AS position,
  -- The traceability banner the LLM prompt expects, e.g.
  -- "006Rg0000012345678 | Created: 2026-03-04 | <call id> | Seg 2 of 3 | Call date: ... | 72s"
  concat(
    sf.opportunity_id, ' | Created: ', sf.created_datetime,
    ' | ', t.id,
    ' | Seg ', row_number() OVER (PARTITION BY t.phone10 ORDER BY t.recordingStartTime),
    ' of ',  count(*)      OVER (PARTITION BY t.phone10),
    ' | Call date: ', t.recordingStartTime,
    ' | ', t.interactionDurationSeconds, 's'
  ) AS combined_key
FROM valid t
-- INNER join: the original did a LEFT join then filtered to matches, which is an inner join.
JOIN ${catalog}.${schema}.dim_salesforce_opportunity sf
  ON sf.contact_phone = t.phone10
-- Scope the analysis to the two demo regions (out-of-region opportunities are dropped here).
WHERE sf.region IN ('${region_1}', '${region_2}');
