# Databricks notebook source
# MAGIC %md
# MAGIC # Setup — supporting objects for the Offer-Blocker POC
# MAGIC
# MAGIC This notebook runs **once, before the pipeline**. It creates the things the
# MAGIC pipeline reads but does not own. None of this is "AI" — it is plumbing and
# MAGIC synthetic reference data so the demo is self-contained.
# MAGIC
# MAGIC It creates:
# MAGIC 1. Two **Volumes** — `landing` (where transcript files arrive for Auto Loader)
# MAGIC    and `seeds` (kept for convenience).
# MAGIC 2. Copies the **sample transcript batch** into the landing Volume.
# MAGIC 3. `dim_salesforce_opportunity` — **synthetic** CRM data. The real workflow joins
# MAGIC    transcripts to Salesforce on phone number to learn each call's *opportunity*
# MAGIC    (a sales deal) and its *stage*/*region*. Our sample transcripts have no such
# MAGIC    fields, so we fabricate a small, deterministic Salesforce table keyed to the
# MAGIC    phone numbers actually present in the sample.
# MAGIC 4. `dim_code_categories` — the catalog of the six blocker codes 4A–4F.
# MAGIC 5. `prompt_offer_blocker` — a 1-row table holding the large LLM instruction prompt.

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

# MAGIC %md ## 1. Volumes — landing zone (Auto Loader source) and seeds

# COMMAND ----------

# A Volume is a Unity-Catalog-governed folder for files. `landing/transcripts` is
# where new transcript batches are dropped; the pipeline's Auto Loader watches it.
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.landing")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.seeds")

LANDING_DIR = f"/Volumes/{CATALOG}/{SCHEMA}/landing/transcripts"
import os
os.makedirs(LANDING_DIR, exist_ok=True)
print("landing dir:", LANDING_DIR)

# COMMAND ----------

# MAGIC %md ## 2. Copy the sample transcript batch into the landing Volume
# MAGIC The sample (`data/batch_b_ny_001.json`) is a JSON **array** of 19 call
# MAGIC transcript records. Copying it here gives Auto Loader a file to ingest.

# COMMAND ----------

import shutil
src_json = f"{FILES_PATH}/data/batch_b_ny_001.json"
dst_json = f"{LANDING_DIR}/batch_b_ny_001.json"
shutil.copyfile(src_json, dst_json)
print(f"copied {src_json} -> {dst_json}  ({os.path.getsize(dst_json)} bytes)")

# COMMAND ----------

# MAGIC %md ## 3. Synthetic `dim_salesforce_opportunity`
# MAGIC One row per phone number found in the sample. Each phone maps to exactly ONE
# MAGIC opportunity (kept 1:1 so the phone-join doesn't multiply rows). We deliberately
# MAGIC place a few opportunities OUT of the demo regions so you can see the region
# MAGIC filter drop them. All values are deterministic (seeded by the phone) so re-runs
# MAGIC are stable.

# COMMAND ----------

import json, re, hashlib
from datetime import datetime, timedelta

def normalize_phone(p: str) -> str:
    """Same rule the pipeline uses: strip non-digits; if >=11 digits keep last 10
    (drops the US country code '1'). Returns '' if not a usable 10-digit number."""
    if p is None:
        return ""
    digits = re.sub(r"\D", "", str(p))
    if len(digits) >= 11:
        digits = digits[-10:]
    return digits if len(digits) == 10 else ""

# Read the raw sample directly in Python (small file) to collect the phone numbers.
with open(src_json, "r", encoding="utf-8") as f:
    records = json.load(f)

phones = sorted({normalize_phone(r.get("clientPhoneNumber")) for r in records} - {""})
print(f"{len(phones)} distinct usable phone numbers in the sample")

# Deterministic attribute assignment.
STAGES = ["Open", "Closed Won", "Closed Lost"]
IN_REGIONS = ["New York", "New Jersey"]
OUT_REGIONS = ["Ontario", "Massachusetts", "Connecticut"]  # excluded by the region filter

def sf_opp_id(phone: str) -> str:
    """Fabricate a realistic-looking 18-char Salesforce Opportunity ID from the phone."""
    h = hashlib.md5(phone.encode()).hexdigest().upper()
    body = "".join(c for c in h if c.isalnum())[:8]
    return ("006Rg00000" + body)[:18].ljust(18, "0")

rows = []
n = len(phones)
for i, phone in enumerate(phones):
    # Put the LAST 3 phones out-of-region to prove the filter works; the rest in NY/NJ.
    if i >= n - 3:
        region = OUT_REGIONS[i % len(OUT_REGIONS)]
    else:
        region = IN_REGIONS[i % len(IN_REGIONS)]
    stage = STAGES[i % len(STAGES)] if i % 4 != 3 else "Closed Won"  # bias toward Open/Closed Won
    created = (datetime(2026, 3, 1) + timedelta(days=(i * 3) % 40)).strftime("%Y-%m-%d %H:%M:%S")
    rows.append((phone, sf_opp_id(phone), stage, region, created))

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

# MAGIC %md ## 4. `dim_code_categories` — the 4A–4F blocker-code catalog
# MAGIC Loaded from `seeds/code_categories.csv`. Two jobs downstream:
# MAGIC (a) supplies the human-readable "Code Name" for each code, and
# MAGIC (b) supplies the **labels + definitions** that the CORE `ai_classify` step uses
# MAGIC to decide which blocker code(s) a call contains.

# COMMAND ----------

import pandas as pd
cc_pdf = pd.read_csv(f"{FILES_PATH}/seeds/code_categories.csv", dtype=str).fillna("")
cc_df = spark.createDataFrame(cc_pdf)  # columns: code, category, description, definition
cc_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.dim_code_categories")
print(f"wrote dim_code_categories ({cc_df.count()} rows)")
display(cc_df)

# COMMAND ----------

# MAGIC %md ## 5. `prompt_offer_blocker` — the LLM instruction prompt (1 row)
# MAGIC The full "how to code offer blockers" rubric (Sections 1–7 of the original
# MAGIC Word doc) is too large and quote-heavy to inline in SQL, so it lives here and
# MAGIC is CROSS JOINed onto every opportunity in the pipeline.

# COMMAND ----------

with open(f"{FILES_PATH}/seeds/offer_blocker_prompt_v6.txt", "r", encoding="utf-8") as f:
    prompt_text = f.read()

prompt_df = spark.createDataFrame(
    [("offer_blocker", prompt_text)], schema="module STRING, prompt_text STRING")
prompt_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.prompt_offer_blocker")
print(f"wrote prompt_offer_blocker (prompt length = {len(prompt_text)} chars)")

# COMMAND ----------

# MAGIC %md ## Done
# MAGIC Supporting objects are ready. Now run the pipeline:
# MAGIC `databricks bundle run offer_blocker_pipeline -t dev -p dbw-brlui-stable`
