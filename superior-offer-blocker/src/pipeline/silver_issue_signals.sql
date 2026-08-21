-- ============ [CORE — task-specific AI Functions doing real work, not just ai_query] ============
-- WHAT THIS STEP DOES
--   Two lightweight, task-specific AI Functions run once per opportunity to produce
--   "signals" that steer (and cross-check) the main analysis:
--     * ai_classify -> which blocker code(s) 4A–4F are present in the conversation.
--     * ai_extract  -> the quoted per-unit price(s) mentioned (named-entity extraction).
--   These feed gold_findings_raw as hints, and are cross-checked there against the
--   detailed findings. They demonstrate that task functions — not only the general
--   ai_query — carry real weight in the CORE path.
--
-- WHY LABELS ARE INLINED HERE
--   ai_classify needs its label set as a constant expression. The labels below mirror
--   the authoritative `dim_code_categories` catalog (which is ALSO used elsewhere to
--   supply each code's display name). Edit both together if the taxonomy changes.
--
-- DOMAIN NOTES (the six offer-blocker codes)
--   4A Rate uncompetitive · 4B Ancillary fees · 4C Commercial model mismatch ·
--   4D Contract mechanics · 4E Availability/serviceability · 4F Promotion ineligibility.

CREATE OR REFRESH MATERIALIZED VIEW silver_issue_signals
COMMENT 'Per-opportunity AI signals: candidate blocker codes (ai_classify) + quoted rate (ai_extract).'
AS
WITH scored AS (
  SELECT
    d.opportunity_id,
    -- ai_classify (multi-label): tag every blocker code that appears in the call.
    -- Returns VARIANT {response:[...codes...], error_message}. Called ONCE here.
    ai_classify(
      d.transcript_text,
      '{
        "4A":"Rate/price uncompetitive: the customer says the quoted per-unit rate is too high, or worse than a competitor or their current supplier.",
        "4B":"Ancillary fees: delivery, tank rental, installation, inspection, monitoring, or admin fees break the economics of the deal.",
        "4C":"Commercial model mismatch: the customer wants a different deal shape (pre-buy, tank ownership, fixed vs variable pricing, commitment length) than Superior offers.",
        "4D":"Contract mechanics: auto-renewal, exit/cancellation terms, or payment/billing terms are the barrier.",
        "4E":"Availability or serviceability: Superior structurally cannot provide the product, equipment, coverage area, or required delivery/install timeline.",
        "4F":"Promotion ineligibility: the customer wanted a specific promotion, credit, or referral discount and could not get it."
      }',
      map('version', '2.0', 'multilabel', 'true')
    ) AS cls,
    -- ai_extract (named-entity recognition): pull the price(s) discussed on the call.
    -- Returns VARIANT {response:{quoted_unit_rate, competitor_or_current_supplier_rate}, ...}.
    ai_extract(
      d.transcript_text,
      '["quoted_unit_rate","competitor_or_current_supplier_rate"]',
      map('version', '2.1')
    ) AS ext
  FROM silver_opportunity_dialogue d
)
SELECT
  opportunity_id,
  -- Convert the VARIANT array of codes into a proper ARRAY<STRING> for later checks.
  from_json(to_json(cls:response), 'ARRAY<STRING>')            AS candidate_codes,
  cls:error_message::STRING                                    AS classify_error,
  -- The rate the rep quoted (e.g. "2.04/gal"); NULL if none was stated.
  -- ai_extract v2.1 returns each field wrapped as {"value": ...}, so read :value
  -- (this yields SQL NULL when the model found nothing, which is what we want).
  ext:response:quoted_unit_rate:value::STRING                     AS quoted_rate,
  ext:response:competitor_or_current_supplier_rate:value::STRING  AS competitor_rate,
  ext:error_message::STRING                                    AS extract_error
FROM scored;
