-- ============ [ENHANCEMENT — new AI-Function capability, NOT in original/] ============
-- WHAT THIS STEP DOES (all NET-NEW vs the original workflow)
--   Enriches EACH call (segment) with a single pass of five task-specific AI
--   Functions, patterned after the Databricks "automated-claims-processing" solution
--   but adapted to propane sales. None of these feed back into the CORE findings —
--   they are extra signals for dashboards, routing, and compliance.
--
--   * ai_analyze_sentiment -> call_tone           : customer's emotional tone.
--   * ai_classify          -> call_topic          : what the call was about (routing).
--   * ai_extract           -> CRM entities        : names, supplier, tank size, city, etc.
--   * ai_summarize         -> call_summary        : a short agent-facing recap.
--   * ai_mask              -> call_summary_masked : the summary with PII redacted (compliance).
--
-- NOTE ON ORDERING: we mask the SUMMARY (not the raw transcript) — cheaper and it
--   mirrors the reference solution. One row per call; blank voicemail calls are skipped.

CREATE OR REFRESH MATERIALIZED VIEW gold_call_enrichment_enh
COMMENT 'ENHANCEMENT: per-call sentiment, topic, entities, summary, and PII-masked summary.'
AS
WITH calls AS (
  SELECT
    id                AS call_id,
    opportunity_id,
    stage_name,
    recordingStartTime,
    -- Full dialogue (both speakers) for topic/entities/summary.
    concat_ws('\n',
      transform(
        filter(interwovenTranscript.transcriptBlock, b -> b.text IS NOT NULL AND length(trim(b.text)) > 0),
        b -> concat(b.channelName, ': ', b.text)
      )
    ) AS call_text,
    -- Customer-only text for tone (we want the CUSTOMER's sentiment, not the agent's).
    concat_ws('\n',
      transform(
        filter(interwovenTranscript.transcriptBlock, b -> b.channelName = 'CLIENT' AND b.text IS NOT NULL AND length(trim(b.text)) > 0),
        b -> b.text
      )
    ) AS client_text
  FROM silver_transcript_sf_joined
),
enriched AS (
  SELECT
    *,
    -- [ENHANCEMENT] ai_analyze_sentiment: positive / negative / neutral / mixed.
    ai_analyze_sentiment(client_text) AS call_tone,
    -- [ENHANCEMENT] ai_classify: single best topic label (for routing/dashboards).
    ai_classify(
      call_text,
      '{
        "new_business":"A prospect exploring switching to or starting new propane/oil service.",
        "billing_payment":"Invoices, payments, budget plans, or pricing disputes.",
        "renewal":"Renewing or re-signing an existing agreement.",
        "delivery_scheduling":"Scheduling or changing a fuel delivery or will-call.",
        "service_equipment":"Tank, installation, safety, or equipment service issues.",
        "cancellation":"Ending, or threatening to end, service.",
        "general_inquiry":"Anything else / a general question."
      }',
      map('version', '2.0')
    ):response[0]::STRING AS call_topic,
    -- [ENHANCEMENT] ai_extract: named-entity extraction of useful CRM fields.
    ai_extract(
      call_text,
      '["customer_full_name","current_supplier","competitor_or_quoted_rate","tank_size","service_city","promotion_mentioned"]',
      map('version', '2.1')
    ):response AS entities,
    -- [ENHANCEMENT] ai_summarize: a <=40-word recap to help an agent prioritize.
    ai_summarize(call_text, 40) AS call_summary
  FROM calls
  WHERE length(trim(call_text)) > 0   -- skip blank voicemail/hangup segments (save cost)
)
SELECT
  call_id,
  opportunity_id,
  stage_name,
  recordingStartTime,
  call_tone,
  call_topic,
  -- Flatten the extracted entities (VARIANT) into plain columns. ai_extract v2.1
  -- wraps each field as {"value": ...}, so read :value (SQL NULL when not found).
  entities:customer_full_name:value::STRING          AS customer_full_name,
  entities:current_supplier:value::STRING            AS current_supplier,
  entities:competitor_or_quoted_rate:value::STRING   AS competitor_or_quoted_rate,
  entities:tank_size:value::STRING                   AS tank_size,
  entities:service_city:value::STRING                AS service_city,
  entities:promotion_mentioned:value::STRING         AS promotion_mentioned,
  call_summary,
  -- [ENHANCEMENT] ai_mask: redact person/address/phone/email for compliant sharing.
  ai_mask(call_summary, array('person', 'address', 'phone', 'email')) AS call_summary_masked
FROM enriched;
