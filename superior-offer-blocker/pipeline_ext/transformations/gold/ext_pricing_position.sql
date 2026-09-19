-- =============================================================================
-- [GENIE ONE EXTENSION — ADDITIVE ONLY] ext_pricing_position
-- -----------------------------------------------------------------------------
-- Pricing fact: one row per opportunity with Superior's quoted per-unit rate vs the
-- competitor/current-supplier rate the customer cited, the derived rate gap, and a
-- deterministic synthetic list rate + fee load. Feeds mv_pricing and
-- account_retention_base.
--
-- REAL SIGNAL: quoted_rates + competitor_rate come from the EXISTING ai_extract
-- output in gold_opportunity_enrichment (read-only). SYNTHETIC (labeled): list_rate
-- and fee_load are deterministic per opportunity_id.
--
-- ADDITIVE: reads gold_opportunity_enrichment only; writes a NEW table.
-- =============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ext_pricing_position
COMMENT 'Additive Genie One extension: per-opportunity price posture. quoted vs competitor rate (real, from ai_extract) + synthetic list_rate/fee_load.'
AS
WITH base AS (
  SELECT
    e.opportunity_id,
    e.stage_name,
    -- final quoted per-unit rate Superior offered (last element of the array)
    element_at(e.quoted_rates, -1).amount                         AS quoted_rate,
    -- first competitor / current-supplier rate the client mentioned
    try_cast(e.competitor_rate:[0]:amount:value AS DOUBLE)        AS competitor_rate
  FROM gold_opportunity_enrichment e
)
SELECT
  b.opportunity_id,
  b.stage_name,
  b.quoted_rate,
  b.competitor_rate,
  -- Rate gap vs competitor (positive => Superior quoting ABOVE market).
  -- The real ai_extract rates are sparse (NULL for most opps on the demo sample), so the
  -- gap is computed from real values WHEN BOTH exist, otherwise it falls back to a LABELED
  -- synthetic gap keyed to the SAME wounded-cohort predicate used by the delivery
  -- generator (abs(hash(opportunity_id)) % 100 < 30). This makes the gap VARY and land
  -- positive on the wounded cohort so the churn-bomb (rate pressure + verified service
  -- failure) surfaces on the same accounts. Values are deterministic and labeled synthetic.
  COALESCE(
    CASE WHEN b.quoted_rate IS NOT NULL AND b.competitor_rate IS NOT NULL
         THEN ROUND(b.quoted_rate - b.competitor_rate, 4) END,
    CASE WHEN abs(hash(b.opportunity_id)) % 100 < 30
         -- wounded: quoting +$0.08 to +$0.27 above market
         THEN ROUND(0.08 + (abs(hash(b.opportunity_id)) % 20) / 100.0, 4)
         -- healthy: at/below market, -$0.15 to +$0.04
         ELSE ROUND(-0.15 + (abs(hash(b.opportunity_id)) % 20) / 100.0, 4)
    END
  )                                                                AS rate_gap_vs_competitor,
  -- rate-pressure flag: positive gap => customer is being quoted above market (labeled)
  CASE WHEN abs(hash(b.opportunity_id)) % 100 < 30 THEN 1 ELSE 0 END AS rate_pressure_flag,
  -- synthetic list rate: quoted rate nudged up deterministically (labeled)
  ROUND(COALESCE(b.quoted_rate, 2.499) * (1.0 + (abs(hash(b.opportunity_id)) % 8) / 100.0), 4) AS list_rate,
  -- synthetic monthly fee load $0-$45 deterministic (labeled)
  ROUND((abs(hash(concat(b.opportunity_id, 'fee'))) % 46), 2)      AS fee_load,
  TRUE AS is_synthetic
FROM base b;
