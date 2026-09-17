-- =============================================================================
-- [GENIE ONE EXTENSION — ADDITIVE ONLY] ext_cx_contact
-- -----------------------------------------------------------------------------
-- CX / contact-center fact: one row per call, surfacing the NICE CXone operational
-- fields that are ALREADY ingested in bronze_transcripts but never exposed as their
-- own analytical surface. Feeds mv_cx_service and account_retention_base.
--
-- ADDITIVE: reads bronze_transcripts + dim_salesforce_opportunity (read-only);
-- writes a NEW table. Does NOT modify the existing silver/gold sales branch.
--
-- PRESERVES NON-SALES CALLS: unlike silver_transcript_sf_joined (an INNER join on
-- phone that drops unmatched calls), this uses a LEFT JOIN so every call survives
-- with a nullable opportunity_id. The retention base view filters to matched opps;
-- the CX Agent can still analyze the full contact population.
--
-- NOTE: hold/queue/abandon/csat/agent fields are inferred (schema-evolved) columns
-- in bronze; try_* / coalesce guard against their absence in a given batch.
-- =============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ext_cx_contact
COMMENT 'Additive Genie One extension: one row per call with contact-center ops metrics (hold, queue, abandon, CSAT, agent/team). Non-sales calls preserved via LEFT JOIN.'
AS
WITH normalized AS (
  SELECT
    b.id                                                        AS call_id,
    right(regexp_replace(b.clientPhoneNumber, '[^0-9]', ''), 10) AS phone10,
    b.recordingStartTime,
    b.interactionDurationSeconds,
    -- ops fields (inferred columns; guard for missing/typed values)
    try_cast(b.holdSeconds       AS INT)     AS hold_seconds,
    try_cast(b.inQueueSeconds    AS INT)     AS in_queue_seconds,
    try_cast(b.abandonSeconds    AS INT)     AS abandon_seconds,
    try_cast(b.totalDurationSeconds AS INT)  AS total_duration_seconds,
    try_cast(b.abandoned         AS BOOLEAN) AS abandoned,
    CAST(b.agentName    AS STRING)           AS agent_name,
    CAST(b.teamName     AS STRING)           AS team_name,
    CAST(b.skillName    AS STRING)           AS skill_name,
    CAST(b.csatSentiment AS STRING)          AS csat_sentiment,
    try_cast(b.csatSentimentIndexScore AS DOUBLE) AS csat_index,
    CAST(b.dispositionCode AS STRING)        AS disposition_code
  FROM bronze_transcripts b
)
SELECT
  n.call_id,
  o.opportunity_id,                         -- nullable: non-sales/unmatched calls kept
  o.region,
  o.stage_name,
  n.recordingStartTime,
  n.hold_seconds,
  n.in_queue_seconds,
  n.abandon_seconds,
  n.total_duration_seconds,
  CASE WHEN COALESCE(n.abandoned, false) OR COALESCE(n.abandon_seconds, 0) > 0
       THEN 1 ELSE 0 END                    AS abandon_flag,
  n.agent_name,
  n.team_name,
  n.skill_name,
  n.csat_sentiment,
  n.csat_index,
  n.disposition_code,
  CASE WHEN o.opportunity_id IS NULL THEN 'unmatched' ELSE 'matched' END AS match_status
FROM normalized n
LEFT JOIN dim_salesforce_opportunity o
  ON o.contact_phone = n.phone10;
