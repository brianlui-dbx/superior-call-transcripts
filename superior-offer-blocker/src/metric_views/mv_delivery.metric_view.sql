-- [GENIE ONE EXTENSION — ADDITIVE] mv_delivery (governed Metric View)
-- Single-fact source (ext_delivery_order). Requires DBR 17.3+ for metadata.
CREATE OR REPLACE VIEW ${catalog}.${schema}.mv_delivery
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
source: ${catalog}.${schema}.ext_delivery_order
comment: "Propane delivery reliability: verified runouts, late deliveries, gallons. One row per delivery order. Values are synthetic (is_synthetic = true)."
dimensions:
  - name: Order Status
    expr: order_status
    synonyms: ["status", "delivery status"]
  - name: Delivery Month
    expr: "DATE_TRUNC('MONTH', delivery_date)"
    format: {type: date, date_format: year_month_day}
measures:
  - name: Orders
    expr: COUNT(1)
    synonyms: ["deliveries", "delivery orders"]
  - name: Runout Rate
    expr: AVG(runout_verified_flag)
    comment: "Share of orders with a verified runout (operational record required — never inferred)."
    format: {type: percentage, decimal_places: {type: exact, places: 1}}
    synonyms: ["runouts", "runout percentage"]
  - name: Late Delivery Rate
    expr: AVG(late_delivery_flag)
    format: {type: percentage, decimal_places: {type: exact, places: 1}}
    synonyms: ["late rate", "on-time miss rate"]
  - name: Verified Failures
    expr: COUNT(1) FILTER (WHERE runout_verified_flag = 1 OR late_delivery_flag = 1)
    synonyms: ["service failures", "failed deliveries"]
  - name: Total Gallons
    expr: SUM(gallons)
    format: {type: number, decimal_places: {type: exact, places: 0}}
$$
