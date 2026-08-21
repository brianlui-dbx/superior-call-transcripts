-- ============ [CORE — like-for-like with original/offer_blocker.py (format_transcripts)] ============
-- WHAT THIS STEP DOES
--   Collapses all the calls of one opportunity into a single, prompt-ready
--   transcript string, exactly like the original `format_transcripts()` function:
--   for each call it writes a banner (Segment ID + the combined_key traceability
--   line) followed by the dialogue turns ("AGENT: ...", "CLIENT: ..."), then
--   concatenates the calls in chronological order. One row per opportunity.
--
-- DATA-QUALITY EXPECTATIONS (replace the manual "STOP and report" rule)
--   The original human workflow was told to stop and report if a segment's
--   "Seg X of N" numbering had gaps. Here that becomes pipeline Expectations:
--   malformed opportunities are dropped (quarantined) instead of failing the run.

CREATE OR REFRESH MATERIALIZED VIEW silver_opportunity_dialogue (
  -- Positions must run 1..N with no gaps/repeats: max position = N AND distinct count = N.
  CONSTRAINT contiguous_positions EXPECT (max_pos = seg_count AND distinct_pos = seg_count) ON VIOLATION DROP ROW,
  CONSTRAINT has_opp_id           EXPECT (opportunity_id IS NOT NULL) ON VIOLATION DROP ROW
)
COMMENT 'One prompt-ready dialogue string per opportunity (all its calls, in call order).'
AS
WITH per_segment AS (
  SELECT
    opportunity_id,
    stage_name,
    position,
    seg_count,
    -- Build one call's block: a banner, then only the non-empty dialogue turns.
    -- transform+filter walk the nested transcriptBlock array (AGENT/CLIENT turns).
    concat(
      '\n============================================\n',
      'Segment ID: ', opportunity_id, '\n',
      combined_key,
      '\n--------------------------------------------\n',
      concat_ws('\n',
        transform(
          filter(interwovenTranscript.transcriptBlock,
                 b -> b.text IS NOT NULL AND length(trim(b.text)) > 0),
          b -> concat(b.channelName, ': ', b.text)
        )
      )
    ) AS segment_block
  FROM silver_transcript_sf_joined
)
SELECT
  opportunity_id,
  any_value(stage_name)     AS stage_name,
  any_value(seg_count)      AS seg_count,       -- N (calls in this opportunity)
  max(position)             AS max_pos,          -- used by the contiguity Expectation
  count(DISTINCT position)  AS distinct_pos,     -- used by the contiguity Expectation
  -- Order the calls by their position, then glue their blocks into one transcript.
  array_join(
    transform(
      array_sort(collect_list(struct(position, segment_block))),  -- sorts by `position`
      x -> x.segment_block
    ),
    '\n'
  ) AS transcript_text
FROM per_segment
GROUP BY opportunity_id;
