# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Cell 1
# MAGIC %md
# MAGIC # Setup — supporting objects for the Offer-Blocker POC
# MAGIC
# MAGIC This notebook runs **once, before the pipeline**. It creates the things the
# MAGIC pipeline reads but does not own. None of this is "AI" — it is plumbing and
# MAGIC synthetic reference data so the demo is self-contained.
# MAGIC
# MAGIC It creates:
# MAGIC 1. A **Volume** — `landing` (where transcript files arrive for Auto Loader).
# MAGIC 2. Copies the **sample transcript batches** into the landing Volume.
# MAGIC 3. `dim_salesforce_opportunity` — CRM data loaded from `seeds/salesforce_opportunities.csv`.
# MAGIC    The real workflow joins transcripts to Salesforce on phone number to learn each
# MAGIC    call's *opportunity* (a sales deal) and its *stage*/*region*. The seed holds the
# MAGIC    real opportunity IDs (from the NY batch docs) and stages (from the "AI Output"
# MAGIC    sheet), keyed to the synthetic phone numbers in the sample transcripts.
# MAGIC 4. `lookup_qualifier_config` — per-code-prefix ai_classify labels & instructions for
# MAGIC    the qualifier step in `gold_findings_raw`.

# COMMAND ----------

# Parameters are injected by the job (see resources/setup.job.yml). Defaults let
# you run the notebook interactively too.
dbutils.widgets.text("catalog", "dbw_brlui_stable")
dbutils.widgets.text("schema", "call_transcripts_poc")
dbutils.widgets.text("files_path", "")  # bundle's synced workspace files root

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
FILES_PATH = dbutils.widgets.get("files_path")

# When run interactively (no files_path), fall back to the current notebook folder.
if not FILES_PATH:
    nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    FILES_PATH = "/Workspace" + "/".join(nb.split("/")[:-2])  # .../files (src/setup/setup -> files)

print(f"CATALOG={CATALOG}  SCHEMA={SCHEMA}  FILES_PATH={FILES_PATH}")

# COMMAND ----------

# DBTITLE 1,Cell 3
# MAGIC %md ## 1. Volume — landing zone (Auto Loader source)

# COMMAND ----------

# DBTITLE 1,Cell 4
# A Volume is a Unity-Catalog-governed folder for files. `landing/transcripts` is
# where new transcript batches are dropped; the pipeline's Auto Loader watches it.
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.landing")

LANDING_DIR = f"/Volumes/{CATALOG}/{SCHEMA}/landing/transcripts"
import os
os.makedirs(LANDING_DIR, exist_ok=True)
print("landing dir:", LANDING_DIR)

# COMMAND ----------

# MAGIC %md ## 2. Copy the sample transcript batches into the landing Volume
# MAGIC Each sample (`data/batch_b_ny_001.json` = 19 calls, `data/batch_b_ny_002.json` = 31 calls)
# MAGIC is a JSON **array** of call transcript records. Copying them here gives Auto Loader
# MAGIC files to ingest.

# COMMAND ----------

import shutil
BATCH_FILES = ["batch_b_ny_001.json", "batch_b_ny_002.json"]
for name in BATCH_FILES:
    src_json = f"{FILES_PATH}/data/{name}"
    dst_json = f"{LANDING_DIR}/{name}"
    shutil.copyfile(src_json, dst_json)
    print(f"copied {src_json} -> {dst_json}  ({os.path.getsize(dst_json)} bytes)")

# COMMAND ----------

# MAGIC %md ## 3. `dim_salesforce_opportunity`
# MAGIC One row per phone number in the samples, loaded from `seeds/salesforce_opportunities.csv`.
# MAGIC Each phone maps to exactly ONE opportunity (kept 1:1 so the phone-join doesn't
# MAGIC multiply rows); an opportunity can have several phones. Stage is blank for
# MAGIC opportunities that don't appear in the "AI Output" sheet.

# COMMAND ----------

import csv, json, re

def normalize_phone(p: str) -> str:
    """Same rule the pipeline uses: strip non-digits; if >=11 digits keep last 10
    (drops the US country code '1'). Returns '' if not a usable 10-digit number."""
    if p is None:
        return ""
    digits = re.sub(r"\D", "", str(p))
    if len(digits) >= 11:
        digits = digits[-10:]
    return digits if len(digits) == 10 else ""

# Read the raw samples directly in Python (small files) to collect the phone numbers.
records = []
for name in BATCH_FILES:
    with open(f"{FILES_PATH}/data/{name}", "r", encoding="utf-8") as f:
        records += json.load(f)

phones = {normalize_phone(r.get("clientPhoneNumber")) for r in records} - {""}
print(f"{len(phones)} distinct usable phone numbers in the samples")

with open(f"{FILES_PATH}/seeds/salesforce_opportunities.csv", newline="", encoding="utf-8") as f:
    seed = list(csv.DictReader(f))

rows = [(r["contact_phone"], r["opportunity_id"], r["stage_name"] or None, r["region"], r["created_datetime"])
        for r in seed]
missing = phones - {r[0] for r in rows}
if missing:
    print(f"WARNING: {len(missing)} phone(s) have no opportunity in the seed and will be dropped by the join: {sorted(missing)}")

from pyspark.sql.types import StructType, StructField, StringType, TimestampType
from pyspark.sql import functions as F

sf_schema = StructType([
    StructField("contact_phone", StringType(), False),   # 10-digit normalized join key
    StructField("opportunity_id", StringType(), False),  # Salesforce Opp ID (the deal)
    StructField("stage_name", StringType(), True),        # Open / Closed Won / Closed Lost
    StructField("region", StringType(), True),            # sales region
    StructField("created_datetime", StringType(), True),  # when the opportunity was opened
])
sf_df = (spark.createDataFrame(rows, sf_schema)
         .withColumn("created_datetime", F.to_timestamp("created_datetime")))
sf_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.dim_salesforce_opportunity")
print(f"wrote dim_salesforce_opportunity ({sf_df.count()} rows)")
display(sf_df.orderBy("region", "opportunity_id"))

# COMMAND ----------

# DBTITLE 1,Cell 13
# MAGIC %md ## 4. `lookup_qualifier_config` — ai_classify labels & instructions per code prefix
# MAGIC Used by `gold_findings_raw` to dynamically route the qualifier classification
# MAGIC without a large CASE statement. One row per 4x code prefix.

# COMMAND ----------

from pyspark.sql import Row

qualifier_rows = [
    Row(
        code_prefix="4A",
        labels_json='{"current-supplier": "Comparison to what customer says their current supplier charges.", "competitor-rate": "A rate or quote from another supplier being shopped (not their current one).", "advertised-rate": "A competitor published or advertised rate cited by the customer.", "high-rate": "Rate too high in absolute terms; no external comparison invoked.", "rate-increase": "Existing or returning customer reacting to a rate increase or renewal price.", "price-match": "Customer demanded a concession: match, discount, or revised quote as condition of proceeding.", "other": "A rate-pressure source no defined value fits."}',
        instructions="Classify the source of rate pressure for code 4A (Rate Competitiveness) in this propane sales call. Precedence: if the customer demanded a concession (match/discount), use price-match and note the comparison source."
    ),
    Row(
        code_prefix="4B",
        labels_json='{"rental/objection": "Tank or equipment rental fee — customer pushed back and it affected progression.", "rental/economics": "Tank or equipment rental fee — structurally uneconomical for customer usage.", "delivery/objection": "Delivery fee — customer pushed back.", "delivery/economics": "Delivery fee — structurally uneconomical for customer usage.", "install/objection": "Installation or setup charge — customer pushed back.", "MUC/objection": "Minimum usage charge — customer pushed back.", "MUC/economics": "Minimum usage charge — structurally uneconomical for customer usage.", "inspection/objection": "Safety or system inspection fee — customer pushed back.", "monitoring/objection": "Tank monitoring or auto-delivery service fee — customer pushed back.", "admin/objection": "Service, admin, or account fee — customer pushed back.", "stack/objection": "Fee stack rejected as a whole.", "other": "Other fee type or ground not covered above."}',
        instructions="Classify the specific fee type and ground (objection = customer pushed back; economics = structurally uneconomical for their usage) for code 4B (Ancillary Fees) in this propane sales call."
    ),
    Row(
        code_prefix="4C",
        labels_json='{"prebuy": "Customer wants pre-buy (fixed volume upfront at locked rate); not offered.", "ownership": "Customer wanted to own their tank and could not: unavailable or conditions made it unviable.", "rate-mechanism": "Rejects the pricing MODEL itself (fixed vs variable, capped, indexed, unknown future pricing).", "commitment-length": "The length of commitment was rejected or required (e.g., 5-year vs 3-year).", "supply-terms": "Exclusivity or minimum volume resisted as a structural requirement.", "delivery-model": "Customer wanted a different delivery model (will-call vs automatic) and was blocked.", "other": "A structural want or rejection no defined pattern fits."}',
        instructions="Classify the specific commercial model mismatch for code 4C in this propane sales call. Route on the customer WANT, not the complaint wording: wanted ownership but blocked -> ownership, even if voiced as fees."
    ),
    Row(
        code_prefix="4D",
        labels_json='{"auto-renewal": "Automatic renewal resisted by the customer.", "exit-terms": "Early-termination charges, cancellation conditions, notice periods, equipment removal, or transfer-on-sale.", "payment-billing": "COD, autopay-required-for-rate, budget-plan gates, or payment window issues.", "escalation-clause": "Resisted adjustment clauses, liability, maintenance responsibility, or property-access rights.", "process": "A required transaction step treated as barrier: e-signature only, prerequisite gating, documentation demands.", "complexity": "Contract as artifact rejected: too long, too much fine print, too complicated.", "other": "A binding mechanic no defined pattern fits."}',
        instructions="Classify the specific contract or transaction mechanic for code 4D in this propane sales call. Fees DURING service -> 4B not here. Fees for LEAVING -> exit-terms. Service gated behind prerequisite -> process."
    ),
    Row(
        code_prefix="4E",
        labels_json='{"service-area": "Location outside serviceable territory or delivery coverage.", "product": "Product type or grade not offered (e.g., cylinder fills, oil in propane-only market).", "equipment": "Tank size, equipment type, or configuration unavailable.", "site": "Access, safety, regulatory, or installation-feasibility limits at the property.", "timeline": "Required delivery or install timeframe could not be met (structural or capacity).", "capability": "A service capability Superior does not offer.", "other": "A supply gap no defined form fits."}',
        instructions="Classify the specific availability or serviceability gap for code 4E in this propane sales call. Must be a PHYSICAL/logistical gap, not commercial model (that is 4C). Timeline includes both structural and capacity-driven delays."
    ),
    Row(
        code_prefix="4F",
        labels_json='{"referral": "Expected referral credit as referred party; only the referrer gets it.", "threshold": "Projected usage below the qualifying volume for promo, waiver, or credit tier.", "ownership": "Owns their tank so leased-tank promos do not apply.", "prior-offer": "References a company rate or offer they saw, had, or heard that cannot be honored today.", "stacking": "Wanted to combine promotions and the stack was denied.", "policy-gate": "Chose a path the promo requires forgoing (refused credit check, chose COD, declined auto-delivery).", "timing": "Promo expired or not yet active in their region.", "other": "An ineligibility ground no defined value fits."}',
        instructions="Classify the specific promotion ineligibility ground for code 4F in this propane sales call. Must be DENIED or INELIGIBLE — not a promo that was successfully applied."
    ),
]

cfg_df = spark.createDataFrame(qualifier_rows)
cfg_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.lookup_qualifier_config"
)
spark.sql(f"ALTER TABLE {CATALOG}.{SCHEMA}.lookup_qualifier_config CLUSTER BY (code_prefix)")
print(f"wrote lookup_qualifier_config ({cfg_df.count()} rows, clustered by code_prefix)")
display(cfg_df)

# COMMAND ----------

# MAGIC %md ## Done
# MAGIC Supporting objects are ready. Now run the pipeline:
# MAGIC `databricks bundle run offer_blocker_pipeline -t dev -p dbw-brlui-stable`