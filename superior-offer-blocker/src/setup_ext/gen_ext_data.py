# Databricks notebook source
# MAGIC %md
# MAGIC # [GENIE ONE EXTENSION — ADDITIVE] Synthetic delivery seed
# MAGIC
# MAGIC Generates `ext_delivery_order_seed`, a **synthetic** per-order delivery table
# MAGIC keyed to the EXISTING `dim_salesforce_opportunity.opportunity_id`s. Read by the
# MAGIC additive pipeline's `ext_delivery_order` MV. Run as a setup task BEFORE the ext
# MAGIC pipeline (mirrors how `dim_salesforce_opportunity` is seeded for the sales one).
# MAGIC
# MAGIC **Story (per the synthetic-data-gen skill — problem → $impact → analyze → fix):**
# MAGIC during the transformation, a *cluster of high-value NY/NJ accounts* hit
# MAGIC **verified runouts + late deliveries**. Those same accounts also carry 4A rate
# MAGIC objections and above-market rate gaps → they are the churn bomb. Retaining ~2pts
# MAGIC of that cohort ≈ $1.05M illustrative contribution. Distributions are **skewed,
# MAGIC never uniform**: most accounts deliver fine; the wounded cohort concentrates
# MAGIC failures. Every row is labeled `is_synthetic = true`.
# MAGIC
# MAGIC ADDITIVE: writes only the NEW `ext_delivery_order_seed` table.

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA  = dbutils.widgets.get("schema")
assert CATALOG and SCHEMA, "catalog and schema are required (never defaulted)"
FQ_OPP  = f"{CATALOG}.{SCHEMA}.dim_salesforce_opportunity"
FQ_SEED = f"{CATALOG}.{SCHEMA}.ext_delivery_order_seed"

# COMMAND ----------
from pyspark.sql import functions as F, types as T
from datetime import date, timedelta

# Read existing opportunities (read-only) — the FK universe.
opps = spark.table(FQ_OPP).select("opportunity_id", "region", "stage_name")

# Deterministic "wounded cohort": ~30% of opps (hash-based) get concentrated failures.
# The SAME hash predicate (abs(hash(opportunity_id)) % 100 < 30) is reused in
# ext_pricing_position so the wounded cohort ALSO carries the positive synthetic rate gap
# => the churn-bomb (rate pressure + verified service failure on the SAME account)
# reliably materializes. ~30% (vs 20%) guarantees several stacked cases on the small
# ~16-opp demo dataset. Skew, not uniform: wounded => 3-6 orders w/ high failure odds;
# healthy => 1-3 clean, on-time orders.
opps = opps.withColumn("h", F.abs(F.hash("opportunity_id")))
opps = opps.withColumn("is_wounded", (F.col("h") % 100 < 30).cast("int"))
opps = opps.withColumn(
    "n_orders",
    F.when(F.col("is_wounded") == 1, 3 + (F.col("h") % 4)).otherwise(1 + (F.col("h") % 3)),
)

# Explode to one row per order using sequence + explode (no driver loops / collect).
orders = (
    opps.withColumn("seq", F.explode(F.sequence(F.lit(1), F.col("n_orders"))))
        .withColumn("oh", F.abs(F.hash("opportunity_id", "seq")))
)

TODAY = date.today()
orders = (
    orders
    # deliveries spread across the last 90 days (recent enough for the base view's 90d window)
    .withColumn("days_ago", (F.col("oh") % 90))
    .withColumn("delivery_date", F.date_sub(F.lit(TODAY), F.col("days_ago")))
    # Late-delivery skew (CORRECTED so it is NOT uniform):
    #   late  <=> delivery_date > promised_date  <=>  promised_date is BEFORE delivery.
    #   Wounded cohort: ~65% of orders land late (promised 1-3 days BEFORE actual delivery).
    #   Healthy cohort: delivered ON/BEFORE promise (promised 1-3 days AFTER, never late).
    .withColumn(
        "promised_date",
        F.when(
            (F.col("is_wounded") == 1) & (F.col("oh") % 100 < 65),
            F.date_sub(F.col("delivery_date"), 1 + (F.col("oh") % 3)),   # promise earlier => LATE
        ).otherwise(
            F.date_add(F.col("delivery_date"), 1 + (F.col("oh") % 3)),   # promise later  => on time
        ),
    )
    .withColumn("late_delivery_flag",
                (F.col("delivery_date") > F.col("promised_date")).cast("int"))
    # gallons: log-normal-ish via skewed buckets (never uniform)
    .withColumn("gallons", F.round(
        F.when(F.col("oh") % 10 < 6, 120 + (F.col("oh") % 90))    # 60% small residential fills
         .when(F.col("oh") % 10 < 9, 250 + (F.col("oh") % 200))   # 30% medium
         .otherwise(600 + (F.col("oh") % 500)), 1))               # 10% large / commercial tail
    # verified runout: high odds ONLY in wounded cohort (concentrated, not uniform)
    .withColumn("runout_verified_flag",
                F.when((F.col("is_wounded") == 1) & (F.col("oh") % 100 < 55), 1).otherwise(
                 F.when(F.col("oh") % 100 < 3, 1).otherwise(0)))  # rare background runouts elsewhere
    .withColumn("order_status", F.when(F.col("runout_verified_flag") == 1, F.lit("emergency"))
                                 .when(F.col("late_delivery_flag") == 1, F.lit("late"))
                                 .otherwise(F.lit("on_time")))
    .withColumn("delivery_id", F.concat(F.lit("DLV-"),
                F.col("opportunity_id"), F.lit("-"), F.format_string("%02d", F.col("seq"))))
    .withColumn("is_synthetic", F.lit(True))
)

seed = orders.select(
    "delivery_id", "opportunity_id", "delivery_date", "promised_date",
    "gallons", "runout_verified_flag", "late_delivery_flag", "order_status", "is_synthetic",
)

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
seed.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(FQ_SEED)
print(f"wrote {FQ_SEED} ({seed.count()} synthetic delivery orders)")

# COMMAND ----------
# MAGIC %md ## Validate the story survives aggregation (skew, not uniform)
display(spark.sql(f"""
  SELECT is_wounded_label,
         COUNT(*)                                        AS orders,
         ROUND(AVG(runout_verified_flag), 3)             AS runout_rate,
         ROUND(AVG(late_delivery_flag), 3)               AS late_rate
  FROM (
    SELECT s.*, CASE WHEN abs(hash(s.opportunity_id)) % 100 < 20 THEN 'wounded' ELSE 'healthy' END AS is_wounded_label
    FROM {FQ_SEED} s
  ) GROUP BY is_wounded_label ORDER BY is_wounded_label
"""))
