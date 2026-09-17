-- =============================================================================
-- [GENIE ONE EXTENSION — ADDITIVE ONLY] account_retention_base
-- -----------------------------------------------------------------------------
-- WHAT THIS IS
--   The multi-fact BASE VIEW that feeds the governed `mv_retention` metric view
--   (see src/metric_views/mv_retention.metric_view.sql). Per the Databricks
--   metric-views skill "one-fact-source" rule: a KPI that combines MULTIPLE fact
--   sources is assembled in a base view first, then the metric view sources it.
--
-- GRAIN: exactly one row per opportunity_id (the existing sales spine).
--
-- ANTI-FAN-OUT RULE (critical):
--   Every source is aggregated to opportunity_id grain in its OWN CTE BEFORE any
--   join. Joining raw calls x deliveries x fees would multiply rows and inflate
--   both counts and dollars. We join only pre-aggregated 1-row-per-opp CTEs.
--
-- ADDITIVE GUARANTEE: reads existing published tables + new ext_* facts;
--   writes a NEW table. It does not modify any existing object.
--
-- SOURCES (all read-only):
--   gold_offer_blocker_summary   (existing) — blocker code / disposition / evidence
--   gold_call_enrichment_enh     (existing) — call_tone, current_supplier, etc.
--   ext_cx_contact               (new)      — NICE CXone ops fields per call
--   ext_pricing_position         (new)      — quoted vs competitor rate, fee load
--   ext_delivery_order           (new)      — synthetic delivery reliability
--   dim_salesforce_opportunity   (existing) — region / stage spine
-- =============================================================================

CREATE OR REFRESH MATERIALIZED VIEW account_retention_base
COMMENT 'Additive Genie One extension: one row per opportunity combining blocker, CX, pricing and delivery signals for retention-aware pricing. Feeds mv_retention.'
AS
WITH
-- 1) Blocker signal, aggregated to one row per opportunity ---------------------
blk AS (
  SELECT
    `Opp ID`                                                        AS opportunity_id,
    MAX(CASE WHEN Disposition IN ('hard_blocker','friction') THEN 1 ELSE 0 END) AS unresolved_blocker_flag,
    MAX(CASE WHEN Code = '4A' AND Disposition IN ('hard_blocker','friction') THEN 1 ELSE 0 END) AS rate_objection_flag,
    MAX_BY(`Code Name`, CASE WHEN Disposition = 'hard_blocker' THEN 2
                             WHEN Disposition = 'friction'     THEN 1 ELSE 0 END) AS primary_blocker_code_name,
    COUNT(*)                                                        AS blocker_finding_count
  FROM gold_offer_blocker_summary
  WHERE Code IS NOT NULL
  GROUP BY `Opp ID`
),
-- 2) Voice-of-customer enrichment, aggregated to one row per opportunity -------
voc AS (
  SELECT
    opportunity_id,
    MAX(CASE WHEN lower(call_tone) IN ('negative','frustrated','angry') THEN 1 ELSE 0 END) AS negative_tone_flag,
    MAX_BY(current_supplier, recordingStartTime)                    AS latest_current_supplier,
    ROUND(AVG(objection_proximity), 4)                              AS avg_objection_proximity
  FROM gold_call_enrichment_enh
  GROUP BY opportunity_id
),
-- 3) Contact-center ops, aggregated to one row per opportunity -----------------
cx AS (
  SELECT
    opportunity_id,
    ROUND(AVG(hold_seconds), 1)                                     AS avg_hold_seconds,
    MAX(CASE WHEN abandon_flag = 1 THEN 1 ELSE 0 END)               AS any_abandon_flag,
    CASE WHEN COUNT(*) > 1 THEN 1 ELSE 0 END                        AS repeat_contact_flag,
    ROUND(AVG(csat_index), 3)                                       AS avg_csat_index,
    COUNT(*)                                                        AS contact_count
  FROM ext_cx_contact
  WHERE opportunity_id IS NOT NULL
  GROUP BY opportunity_id
),
-- 4) Pricing posture, aggregated to one row per opportunity --------------------
px AS (
  SELECT
    opportunity_id,
    ROUND(AVG(rate_gap_vs_competitor), 4)                           AS rate_gap_vs_competitor,
    ROUND(AVG(fee_load), 2)                                         AS fee_load
  FROM ext_pricing_position
  GROUP BY opportunity_id
),
-- 5) Delivery reliability, aggregated to one row per opportunity ---------------
del AS (
  SELECT
    opportunity_id,
    MAX(runout_verified_flag)                                       AS runout_verified_flag,
    MAX(late_delivery_flag)                                         AS late_delivery_flag,
    COUNT(*) FILTER (WHERE runout_verified_flag = 1 OR late_delivery_flag = 1) AS verified_failure_count,
    ROUND(SUM(gallons), 1)                                          AS gallons_90d
  FROM ext_delivery_order
  WHERE delivery_date >= date_sub(current_date(), 90)
  GROUP BY opportunity_id
)
SELECT
  o.opportunity_id,
  o.region,
  o.stage_name,
  -- blocker
  COALESCE(blk.unresolved_blocker_flag, 0)     AS unresolved_blocker_flag,
  COALESCE(blk.rate_objection_flag, 0)         AS rate_objection_flag,
  blk.primary_blocker_code_name,
  COALESCE(blk.blocker_finding_count, 0)       AS blocker_finding_count,
  -- voice
  COALESCE(voc.negative_tone_flag, 0)          AS negative_tone_flag,
  voc.latest_current_supplier,
  voc.avg_objection_proximity,
  -- cx
  cx.avg_hold_seconds,
  COALESCE(cx.any_abandon_flag, 0)             AS any_abandon_flag,
  COALESCE(cx.repeat_contact_flag, 0)          AS repeat_contact_flag,
  cx.avg_csat_index,
  COALESCE(cx.contact_count, 0)                AS contact_count,
  -- pricing
  px.rate_gap_vs_competitor,
  px.fee_load,
  -- delivery
  COALESCE(del.runout_verified_flag, 0)        AS runout_verified_flag,
  COALESCE(del.late_delivery_flag, 0)          AS late_delivery_flag,
  COALESCE(del.verified_failure_count, 0)      AS verified_failure_count,
  del.gallons_90d,
  -- synthetic trailing contribution (labeled): base $600 +/- deterministic spread
  ROUND(600 + (abs(hash(o.opportunity_id)) % 400) - 200, 2) AS trailing_contribution,
  -- rule-based churn-risk tier (NO calibrated probabilities)
  CASE
    WHEN COALESCE(blk.rate_objection_flag,0) = 1 AND COALESCE(del.verified_failure_count,0) > 0 THEN 'High'
    WHEN COALESCE(blk.unresolved_blocker_flag,0) = 1 OR COALESCE(del.verified_failure_count,0) > 0
      OR COALESCE(cx.repeat_contact_flag,0) = 1 THEN 'Medium'
    ELSE 'Low'
  END AS churn_risk_tier,
  -- raise vs protect segment (the strategic call)
  CASE
    WHEN COALESCE(del.verified_failure_count,0) > 0 OR COALESCE(cx.repeat_contact_flag,0) = 1
      OR COALESCE(blk.rate_objection_flag,0) = 1 THEN 'Protect'
    ELSE 'Can Raise'
  END AS raise_vs_protect_segment,
  TRUE AS is_synthetic
FROM dim_salesforce_opportunity o
LEFT JOIN blk ON blk.opportunity_id = o.opportunity_id
LEFT JOIN voc ON voc.opportunity_id = o.opportunity_id
LEFT JOIN cx  ON cx.opportunity_id  = o.opportunity_id
LEFT JOIN px  ON px.opportunity_id  = o.opportunity_id
LEFT JOIN del ON del.opportunity_id = o.opportunity_id;
