-- ============ [ENHANCEMENT — new AI-Function capability, NOT in original/] ============
-- WHAT THIS STEP DOES (NET-NEW vs the original workflow)
--   Uses a SECOND ai_query to draft a ready-to-send follow-up email for each
--   opportunity. Unlike a generic email, ours is "blocker-aware": it summarizes the
--   coded findings for the opportunity and asks the model to acknowledge that
--   specific blocker and propose a concrete next step. Output is strict JSON so a
--   downstream app can render or send it. One row per opportunity.

CREATE OR REFRESH MATERIALIZED VIEW gold_followup_email_enh
COMMENT 'ENHANCEMENT: a strict-JSON follow-up email per opportunity, steered by the coded offer blockers.'
AS
WITH blockers AS (
  -- Roll each opportunity's real findings into one steering line for the email.
  SELECT
    `Opp ID` AS opportunity_id,
    concat_ws('; ',
      collect_list(concat(Code, '/', Qualifier, ' [', Disposition, ']: ', Evidence))
    ) AS blocker_context
  FROM gold_offer_blocker_findings
  WHERE Code <> '—'
  GROUP BY `Opp ID`
),
drafted AS (
  -- One ai_query call per opportunity. failOnError => false so a bad row can't fail
  -- the batch; the call returns STRUCT{response, errorMessage}.
  SELECT
    d.opportunity_id,
    d.stage_name,
    ai_query(
      '${model_endpoint}',   -- same parameterized endpoint the CORE analysis uses
      concat(
        'You are a Superior Plus Propane inside-sales agent. Using the call transcript and the ',
        'identified offer blocker(s), draft a professional, friendly follow-up email to the customer ',
        'that acknowledges their specific concern and proposes a concrete next step. Keep it concise.',
        '\n\nIDENTIFIED BLOCKERS: ', coalesce(b.blocker_context, 'none identified'),
        '\n\nCALL TRANSCRIPT:\n', d.transcript_text
      ),
      responseFormat => '{"type":"json_schema","json_schema":{"name":"followup_email","strict":true,"schema":{"type":"object","additionalProperties":false,"required":["subject","greeting","call_summary","blocker_acknowledgement","recommended_next_step","contact_information","closing"],"properties":{"subject":{"type":"string"},"greeting":{"type":"string"},"call_summary":{"type":"string"},"blocker_acknowledgement":{"type":"string"},"recommended_next_step":{"type":"string"},"contact_information":{"type":"string"},"closing":{"type":"string"}}}}}',
      failOnError => false,
      modelParameters => named_struct('temperature', CAST(0.2 AS DOUBLE), 'max_tokens', 1200)
    ) AS resp
  FROM silver_opportunity_dialogue d
  LEFT JOIN blockers b USING (opportunity_id)
)
SELECT
  opportunity_id,
  stage_name,
  -- with failOnError => false, ai_query returns STRUCT{result, errorMessage}
  resp.result        AS email_json,    -- strict-JSON string; parse with from_json downstream
  resp.errorMessage  AS email_error
FROM drafted;
