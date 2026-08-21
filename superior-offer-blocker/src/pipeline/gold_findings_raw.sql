-- ============ [CORE — like-for-like with original/offer_blocker.py (the LLM call)] ============
-- WHAT THIS STEP DOES
--   Runs the main offer-blocker analysis with ai_query, once per opportunity. This
--   is the direct replacement for the original LangChain/Azure-OpenAI structured
--   call. ai_query is the only function that can return the "N findings, each with
--   8 fields" shape, so it produces the detailed rows; the ai_classify codes and
--   ai_extract rate from silver_issue_signals are passed in as HINTS (and later
--   cross-checked).
--
-- KEY MECHANICS
--   * The large instruction rubric lives in prompt_offer_blocker (CROSS JOINed in).
--   * model_endpoint is a parameter (${model_endpoint}) — swap models with no code change.
--   * responseFormat forces a strict JSON object {"findings":[...]}, so we get
--     machine-readable output instead of the chat-formatted table the original prompt
--     describes. An OUTPUT OVERRIDE note tells the model to keep the CODING LOGIC but
--     drop the chat/worksheet/chunking formatting.
--   * failOnError => false so one bad row never fails the whole batch; the per-row
--     error is captured in ai_response.errorMessage and quarantined downstream.

CREATE OR REFRESH MATERIALIZED VIEW gold_findings_raw
COMMENT 'Raw ai_query output (JSON string) per opportunity, plus the signals used to steer/cross-check it.'
AS
SELECT
  d.opportunity_id,
  d.stage_name,
  s.candidate_codes,                 -- from ai_classify; used for the cross-check downstream
  s.quoted_rate,                     -- from ai_extract; preferred source of the Rate column
  ai_query(
    '${model_endpoint}',
    concat(
      p.prompt_text,
      '\n\n=== AI-DETECTED SIGNALS (hints — verify against the transcript, do not trust blindly) ===',
      '\nCandidate blocker codes (from ai_classify): ', coalesce(array_join(s.candidate_codes, ', '), 'none detected'),
      '\nExtracted quoted rate (from ai_extract): ',    coalesce(s.quoted_rate, 'none stated'),
      '\n\n=== OUTPUT OVERRIDE (automated pipeline) ===\n',
      'Ignore the chat-oriented output instructions in the rubric (worksheet lines, the inventory line, ',
      'chunking into groups, the integrity trailer, and waiting for "next"). Apply ONLY the CODING LOGIC ',
      '(codes 4A-4F, qualifiers, dispositions, confidence, and the evidence discipline). Return ONLY JSON ',
      'matching the provided schema: a single object with a "findings" array holding one item per evaluated ',
      'candidate issue for THIS one opportunity. Set opp_id to the Salesforce Opp ID shown in the banner. ',
      'If the opportunity has no candidate issues, return exactly one finding with code "—", disposition "—", ',
      'and the other fields "—". confidence must be one of High, Medium, Low.\n',
      '\n=== TRANSCRIPTS FOR OPP ', d.opportunity_id, ' ===\n',
      d.transcript_text
    ),
    responseFormat => '{"type":"json_schema","json_schema":{"name":"offer_blocker_findings","strict":true,"schema":{"type":"object","additionalProperties":false,"required":["findings"],"properties":{"findings":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["opp_id","rate","code","primary","qualifier","disposition","confidence","evidence"],"properties":{"opp_id":{"type":"string"},"rate":{"type":"string"},"code":{"type":"string","enum":["4A","4B","4C","4D","4E","4F","—"]},"primary":{"type":"boolean"},"qualifier":{"type":"string"},"disposition":{"type":"string","enum":["hard_blocker","friction","mention_only","resolved","latent","insufficient_evidence","—"]},"confidence":{"type":"string","enum":["High","Medium","Low"]},"evidence":{"type":"string"}}}}}}}}',
    failOnError => false,
    modelParameters => named_struct('temperature', CAST(0.0 AS DOUBLE), 'max_tokens', 4096)
  ) AS ai_response
FROM silver_opportunity_dialogue d
LEFT JOIN silver_issue_signals s USING (opportunity_id)
CROSS JOIN (SELECT prompt_text FROM ${catalog}.${schema}.prompt_offer_blocker WHERE module = 'offer_blocker' LIMIT 1) p;
