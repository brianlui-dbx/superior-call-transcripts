-- ============ [ENHANCEMENT — new AI-Function capability, NOT in original/] ============
-- WHAT THIS STEP DOES (NET-NEW vs the original workflow)
--   Uses a SECOND ai_query to draft a ready-to-send follow-up email for each
--   opportunity. Unlike a generic email, ours is "blocker-aware": it summarizes the
--   coded findings for the opportunity and asks the model to acknowledge that
--   specific blocker and propose a concrete next step. Output is strict JSON so a
--   downstream app can render or send it. One row per opportunity.

CREATE OR REFRESH MATERIALIZED VIEW gold_followup_email_enh
AS
WITH blockers AS (
  -- Roll each opportunity's real findings into one steering line for the email.
  SELECT
    opportunity_id,
    concat_ws('; ',
      collect_list(concat(code, '/', qualifier, ' [', disposition, ']: ', disposition_evidence))
    ) AS blocker_context
  FROM gold_offer_blockers
  WHERE code <> '—'
  GROUP BY opportunity_id
),
drafted AS (
  -- One ai_gen call per opportunity. ai_gen is the built-in general text-generation
  -- AI Function that routes through the workspace's Unity Gateway default model, so it
  -- needs NO explicit serving endpoint (unlike ai_query, whose pay-per-token endpoints
  -- are disabled on Unity-Gateway-only workspaces). The strict-JSON contract is enforced
  -- via an explicit instruction in the prompt instead of ai_query's responseFormat arg.
  SELECT
    d.opportunity_id,
    d.stage_name,
    ai_gen(
      concat(
        'You are a Superior Plus Propane inside-sales agent. Using the call transcript and the ',
        'identified offer blocker(s), draft a professional, friendly follow-up email to the customer ',
        'that acknowledges their specific concern and proposes a concrete next step. Keep it concise.',
        '\n\nReturn ONLY strict minified JSON (no markdown, no code fences) with exactly these keys: ',
        'subject, greeting, call_summary, blocker_acknowledgement, recommended_next_step, ',
        'contact_information, closing. Each value must be a string.',
        '\n\nIDENTIFIED BLOCKERS: ', coalesce(b.blocker_context, 'none identified'),
        '\n\nCALL TRANSCRIPT:\n', d.transcript_text
      )
    ) AS resp
  FROM gold_opportunity_enrichment d
  LEFT JOIN blockers b USING (opportunity_id)
)
SELECT
  opportunity_id,
  stage_name,
  -- ai_gen returns the generated string directly (strict-JSON per the prompt contract);
  -- parse with from_json downstream. email_error is retained for schema compatibility:
  -- it is NULL on success, or the JSON-parse failure reason if the output is malformed.
  resp AS email_json,
  CASE
    WHEN from_json(resp, 'STRUCT<subject:STRING>') IS NULL
    THEN 'ai_gen output was not valid JSON'
    ELSE NULL
  END AS email_error
FROM drafted;
