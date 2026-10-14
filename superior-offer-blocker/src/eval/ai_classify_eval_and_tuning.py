# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# MAGIC %md
# MAGIC # Evaluating & Tuning the `ai_classify` Offer-Blocker Classifier
# MAGIC
# MAGIC **Audience:** you are new to Databricks and MLflow. This single notebook teaches
# MAGIC you how to *think through*, *measure*, and *tune* the prompt behind an
# MAGIC `ai_classify` call — using MLflow as the scaffolding — and, just as importantly,
# MAGIC **when not to over-engineer it**.
# MAGIC
# MAGIC ## What are we evaluating?
# MAGIC In the pipeline, `gold_opportunity_enrichment` runs **one** `ai_classify(...)` call
# MAGIC per sales-call transcript. It is **multilabel**: a transcript can receive 0..N
# MAGIC "offer-blocker" codes (**4A–4F**). The foundation model is fixed — the thing we
# MAGIC actually tune is a **prompt**, and that prompt lives in **two surfaces**:
# MAGIC
# MAGIC 1. the six **label descriptions** (the routing rules per code), and
# MAGIC 2. the global **instructions** string (when to assign *anything* at all).
# MAGIC
# MAGIC > **The one mental model to internalize:** *we are not evaluating a model, we are
# MAGIC > evaluating a prompt.* A "model version" here **is** a `(descriptions +
# MAGIC > instructions + options)` bundle. Evaluation is a function
# MAGIC > `prompt_config -> accuracy metrics`.
# MAGIC
# MAGIC ## The ground truth
# MAGIC `code_classification_eval_dataset` is an **MLflow managed evaluation dataset**
# MAGIC (Unity-Catalog-backed). Each row has an `inputs` JSON (`opportunity_id`,
# MAGIC `transcript_text`) and an `expectations` JSON
# MAGIC (`{"expected_response": "[\"4B\",\"4C\"]"}` — a multilabel array; `[]` = no blocker).
# MAGIC
# MAGIC ## ⚠️ Read this before you read any number
# MAGIC This eval set is **tiny and imbalanced**: **24 rows, 50% empty, and code 4A has
# MAGIC exactly ONE positive example.** That single fact changes everything:
# MAGIC
# MAGIC * We are **not** running an optimization problem. We are running a **structured,
# MAGIC   rationale-driven error analysis** with a *thin quantitative guardrail*.
# MAGIC * Metrics are a **regression smoke-test**, not a leaderboard. One row flipping
# MAGIC   moves micro-F1 by ~4 points — that is **noise**, not progress.
# MAGIC * The honest #1 deliverable is **not a tuned prompt** — it is a credible path from
# MAGIC   24 labels to a set big enough to trust. We return to this at the end.
# MAGIC
# MAGIC The notebook is **idempotent**: run it top-to-bottom any number of times and you
# MAGIC get the same experiment state. Expensive `ai_classify` calls are cached by a
# MAGIC hash of the prompt config, so re-runs are free *and* deterministic.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 0 — Setup, parameters & the prompt config
# MAGIC
# MAGIC **Best practice #1: nothing is hardcoded in a cell.** Everything that could change
# MAGIC between runs is a *widget* (a notebook parameter). Re-running with the same widgets
# MAGIC reproduces the same result exactly — that is the foundation of idempotency.

# COMMAND ----------

# MAGIC %pip install -q -U "mlflow[databricks]>=3.1"
# MAGIC %restart_python

# COMMAND ----------

# Widgets = the notebook's parameters. Defaults let you run interactively; a job can
# override them. Changing a widget and re-running is how you point this at new data.
dbutils.widgets.text("catalog", "dbw_brlui_stable", "Unity Catalog")
dbutils.widgets.text("schema", "call_transcripts_poc", "Schema")
dbutils.widgets.text("eval_table", "code_classification_eval_dataset", "Ground-truth eval dataset")
dbutils.widgets.text("experiment_path", "", "MLflow experiment path (blank = notebook default)")
dbutils.widgets.text("run_label", "baseline_v1", "Human name for THIS prompt variant")
dbutils.widgets.text("confidence_threshold", "0.0", "Keep labels with confidence >= this")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
EVAL_TABLE = f"{CATALOG}.{SCHEMA}.{dbutils.widgets.get('eval_table')}"
CACHE_TABLE = f"{CATALOG}.{SCHEMA}.ai_classify_eval_cache"
RUN_LABEL = dbutils.widgets.get("run_label")
CONFIDENCE_THRESHOLD = float(dbutils.widgets.get("confidence_threshold"))

print(f"Ground truth : {EVAL_TABLE}")
print(f"Cache table  : {CACHE_TABLE}")
print(f"Run label    : {RUN_LABEL}")
print(f"Confidence τ : {CONFIDENCE_THRESHOLD}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### The prompt config — a single versioned object
# MAGIC
# MAGIC The two tunable surfaces (descriptions + instructions) plus the `ai_classify`
# MAGIC options are **one object**. We treat them as a unit, serialize them, and hash them.
# MAGIC That hash becomes the cache key and the thing we log to MLflow — so every result is
# MAGIC traceable to the exact prompt that produced it.
# MAGIC
# MAGIC **To tune:** copy this cell, edit *one* surface, change `run_label`, re-run. Keep the
# MAGIC baseline below byte-for-byte identical to production so your first number reflects
# MAGIC reality.

# COMMAND ----------

# --- Surface 1: the six label DESCRIPTIONS (edit these to fix *boundary* errors) -------
LABELS = {
    "4A. Rate/price uncompetitive": "The customer reacts to the quoted per-unit rate as too high, or compares it unfavourably to a competitor or current supplier. NOT a generic price concern before a specific rate is quoted. NOT a non-rate fee (that is 4B). NOT an objection to rate DESIGN like variability or Year-2 uncertainty (that is 4C rate-mechanism).",
    "4B. Ancillary fees barrier": "Delivery, tank rental, installation, MUC, inspection, monitoring, or admin fees — charges paid WHILE a customer — break the economics or trigger pushback. NOT fees for LEAVING the contract like early-termination (that is 4D). NOT fee objections where the underlying want is tank ownership (that is 4C).",
    "4C. Commercial model mismatch": "The customer wants a fundamentally different deal shape (pre-buy, tank ownership, fixed vs variable pricing, commitment length, delivery model) than Superior offers. Route on the customer WANT, not the complaint wording: wanted ownership but voiced as fees is still 4C. NOT binding mechanics like auto-renewal or exit terms (that is 4D).",
    "4D. Contract/transaction mechanics": "A binding mechanic — how the customer is locked in, gets out, or must transact — is the barrier. Includes auto-renewal, exit/cancellation terms, payment/billing terms, and process barriers (e-signature only, prerequisite gating). Customer accepts the deal shape but resists the machinery. NOT commitment length (that is 4C). NOT fees during service (that is 4B).",
    "4E. Availability/serviceability gap": "Superior cannot physically provide the required product, equipment, coverage area, or timeline. Must be a PHYSICAL or logistical gap. Includes timeline when the customer requires delivery/install by a date that cannot be met. NOT a commercial model preference (that is 4C). NOT when service exists but is gated behind prerequisites (that is 4D).",
    "4F. Promotion ineligibility": "The customer wanted a specific promotion, credit, referral discount, or prior offer and was DENIED or found ineligible. Must be ineligibility or access gap — NOT a promo successfully applied. A Superior offer they cannot access is 4F; a competitor advertised rate is 4A.",
}

# --- Surface 2: the global INSTRUCTIONS (edit this to fix over/under-assignment) --------
INSTRUCTIONS = (
    "You are analyzing sales call transcripts for a propane/energy supplier (Superior) "
    "between Superior's agent and a client. Identify which offer-blocker codes apply "
    "based on what the client explicitly says or demonstrates through behaviour. Key "
    "rules: (1) Only assign a code if there is clear evidence in the dialogue — do not "
    "infer intent beyond what is stated. (2) If the customer's concern dissolved once the "
    "rep gave an accurate explanation, do NOT assign — the offer was not the barrier. "
    "(3) If the REP's handling was the gap (inaccurate, evasive), do NOT assign — that is "
    "a rep-handling issue, not an offer issue. (4) A customer with no genuine switch "
    "intent (benchmarking or price-checking only) has no offer blocker. (5) One-question "
    "litmus for ambiguous cases: complaint about the rate number -> 4A; about a bolt-on "
    "operating charge -> 4B; about the deal shape -> 4C; about what binds them to it -> "
    "4D; about what Superior cannot physically provide -> 4E; about a deal they were "
    "advertised but cannot get -> 4F."
)

# --- ai_classify options (these too are part of the config we version) -----------------
AI_OPTIONS = {
    "version": "2.1",
    "multilabel": "true",
    "enableConfidenceScores": "true",
    "enableRationales": "true",
}

# The ordered list of valid code prefixes we report on. Order is held FIXED across
# variants so we measure the description text, not a label-ordering artifact.
CODE_PREFIXES = ["4A", "4B", "4C", "4D", "4E", "4F"]

# COMMAND ----------

import json
import hashlib

# The config is one object. Serialize deterministically (sorted keys) and hash it.
PROMPT_CONFIG = {"labels": LABELS, "instructions": INSTRUCTIONS, "options": AI_OPTIONS}
_config_blob = json.dumps(PROMPT_CONFIG, sort_keys=True, ensure_ascii=False)
CONFIG_HASH = hashlib.sha256(_config_blob.encode("utf-8")).hexdigest()[:16]
print(f"CONFIG_HASH = {CONFIG_HASH}  (changes whenever ANY surface changes)")

# COMMAND ----------

import mlflow

# Point MLflow at an experiment. Blank => the notebook's own default experiment, which
# is the simplest correct choice for a newcomer. An explicit path lets a team share one.
_exp = dbutils.widgets.get("experiment_path").strip()
if _exp:
    mlflow.set_experiment(_exp)
    print(f"Using experiment: {_exp}")
else:
    print("Using the notebook's default experiment (no path set).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1 — Load the ground truth and LOOK AT IT FIRST
# MAGIC
# MAGIC **Best practice #2: inspect the data before you measure anything.** We parse the
# MAGIC managed dataset's JSON columns into a clean shape and immediately print the class
# MAGIC balance. For a tiny set, this table sets your expectations for *every* number below.
# MAGIC
# MAGIC > *MLflow-native alternative:* you can also load this with
# MAGIC > `mlflow.genai.datasets.get_dataset(name="…")` (requires `databricks-agents`). We
# MAGIC > read it transparently with Spark here so you can see exactly what is inside.

# COMMAND ----------

from pyspark.sql import functions as F

# `inputs` and `expectations` are JSON strings. Parse them into real columns.
raw = spark.table(EVAL_TABLE)
gt = (
    raw.select(
        F.get_json_object("inputs", "$.opportunity_id").alias("opportunity_id"),
        F.get_json_object("inputs", "$.transcript_text").alias("transcript_text"),
        F.get_json_object("expectations", "$.expected_response").alias("expected_json"),
    )
    # expected_response is itself a JSON array string, e.g. '["4B","4C"]' or '[]'
    .withColumn("expected_codes", F.from_json("expected_json", "ARRAY<STRING>"))
    .drop("expected_json")
)
gt.cache()
N_ROWS = gt.count()
print(f"Loaded {N_ROWS} ground-truth rows.")
display(gt.select("opportunity_id", "expected_codes"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Class balance — the single most important table in this notebook

# COMMAND ----------

import pandas as pd

gt_pd = gt.toPandas()
gt_pd["expected_set"] = gt_pd["expected_codes"].apply(lambda a: set(a or []))

n_empty = int((gt_pd["expected_set"].apply(len) == 0).sum())
balance = pd.DataFrame(
    {"code": CODE_PREFIXES,
     "positive_rows": [int(gt_pd["expected_set"].apply(lambda s: c in s).sum()) for c in CODE_PREFIXES]}
)
print(f"Total rows            : {N_ROWS}")
print(f"Empty / no-blocker    : {n_empty}  ({n_empty / N_ROWS:.0%})")
print(f"Pooled label decisions: {N_ROWS * len(CODE_PREFIXES)}  <- the REAL sample size for micro-F1")
display(balance)

print(
    "\n⚠️  READ THE NOISE FLOOR BEFORE ANY METRIC:\n"
    f"   • 1 flipped label ≈ {1 / (N_ROWS * len(CODE_PREFIXES)):.1%} of micro decisions\n"
    f"   • 1 flipped ROW   ≈ ~{len(CODE_PREFIXES) / (N_ROWS * len(CODE_PREFIXES)):.1%} swing in micro-F1\n"
    "   • 4A has ~1 positive example: its per-label F1 is a COIN FLIP, not a metric.\n"
    "   Treat metric moves smaller than ~1 row as NOISE, not progress."
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2 — The system under test: build the `ai_classify` SQL from the config
# MAGIC
# MAGIC Here we turn the Python config object into the exact `ai_classify(...)` SQL the
# MAGIC pipeline runs. We build it programmatically so the prompt the pipeline uses and the
# MAGIC prompt we evaluate can never drift apart.

# COMMAND ----------

def _sql_str(s: str) -> str:
    """Safely embed a Python string as a SQL string literal (escape single quotes)."""
    return "'" + s.replace("'", "''") + "'"

def build_ai_classify_expr(column: str, config: dict) -> str:
    """Render the ai_classify(...) SQL expression for a given prompt config."""
    labels_json = json.dumps(config["labels"], ensure_ascii=False)
    opts = dict(config["options"])
    opts["instructions"] = config["instructions"]
    opt_pairs = ", ".join(f"{_sql_str(k)}, {_sql_str(v)}" for k, v in opts.items())
    return f"ai_classify({column}, {_sql_str(labels_json)}, map({opt_pairs}))"

print(build_ai_classify_expr("transcript_text", PROMPT_CONFIG)[:600], "...")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3 — Reproducibility cache (the heart of idempotency)
# MAGIC
# MAGIC **`ai_classify` is a non-deterministic LLM call.** Run it twice on the same row and
# MAGIC the answer can differ. If we re-scored live every run, our "idempotent notebook"
# MAGIC claim would be a lie and a newcomer would panic when numbers wobble.
# MAGIC
# MAGIC So we **run the model once per `config_hash` and cache the result** in a Delta
# MAGIC table. Same config → same predictions → same metrics, forever. The cache is also
# MAGIC our audit trail: every prediction is tagged with the prompt that produced it.
# MAGIC
# MAGIC > At 24 rows the cost saving is pennies — the real win is **determinism**. We use
# MAGIC > `CREATE TABLE IF NOT EXISTS` + delete-then-insert *for this hash only*, never
# MAGIC > `CREATE OR REPLACE` (which would wipe other variants and break re-runs).

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CACHE_TABLE} (
  config_hash      STRING,
  opportunity_id   STRING,
  pred_codes       ARRAY<STRING>,
  pred_confidences ARRAY<DOUBLE>,
  pred_rationales  ARRAY<STRING>,
  scored_at        TIMESTAMP
)
""")

already = spark.sql(
    f"SELECT COUNT(*) AS n FROM {CACHE_TABLE} WHERE config_hash = '{CONFIG_HASH}'"
).collect()[0]["n"]
print(f"Cached rows for this config: {already} / {N_ROWS}")

# COMMAND ----------

def classify_and_cache(config: dict, config_hash: str) -> None:
    """Run ai_classify over the eval inputs for one config and persist to the cache.
    Idempotent: skips entirely if this config_hash is already fully cached."""
    have = spark.sql(
        f"SELECT COUNT(*) AS n FROM {CACHE_TABLE} WHERE config_hash = '{config_hash}'"
    ).collect()[0]["n"]
    if have >= N_ROWS:
        print(f"✓ config {config_hash} already cached ({have} rows) — skipping LLM calls.")
        return

    print(f"Running ai_classify for config {config_hash} over {N_ROWS} rows …")
    gt.select("opportunity_id", "transcript_text").createOrReplaceTempView("_eval_inputs")
    expr = build_ai_classify_expr("transcript_text", config)

    # cls:response is ARRAY<STRUCT<value, confidence_score, rationale>>; pull the 3 arrays.
    scored = spark.sql(f"""
      WITH raw AS (
        SELECT opportunity_id, {expr} AS cls FROM _eval_inputs
      )
      SELECT
        '{config_hash}' AS config_hash,
        opportunity_id,
        transform(cls:response::ARRAY<STRUCT<value:STRING,confidence_score:DOUBLE,rationale:STRING>>,
                  x -> x.value)            AS pred_codes,
        transform(cls:response::ARRAY<STRUCT<value:STRING,confidence_score:DOUBLE,rationale:STRING>>,
                  x -> x.confidence_score) AS pred_confidences,
        transform(cls:response::ARRAY<STRUCT<value:STRING,confidence_score:DOUBLE,rationale:STRING>>,
                  x -> x.rationale)        AS pred_rationales,
        current_timestamp()                AS scored_at
      FROM raw
    """)

    # Delete-then-insert for THIS hash only => idempotent, leaves other variants intact.
    scored.createOrReplaceTempView("_scored")
    spark.sql(f"DELETE FROM {CACHE_TABLE} WHERE config_hash = '{config_hash}'")
    spark.sql(f"INSERT INTO {CACHE_TABLE} SELECT * FROM _scored")
    print(f"✓ cached {scored.count()} predictions for config {config_hash}.")

classify_and_cache(PROMPT_CONFIG, CONFIG_HASH)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4 — Deterministic scorers (no LLM judge needed)
# MAGIC
# MAGIC **We have ground truth, so we compare sets with plain Python — do not pay an LLM
# MAGIC judge to re-derive labels we already know.** Two kinds of measurement, and knowing
# MAGIC which is which is a core lesson:
# MAGIC
# MAGIC * **Row-wise** metrics (Jaccard, exact-match, "did we abstain correctly?") — MLflow
# MAGIC   `@scorer` functions run per row and let you click into any example in the UI.
# MAGIC * **Corpus-wide** metrics (precision/recall/F1) — these are *not* row averages;
# MAGIC   they need the whole set at once. We compute them in a plain cell (Section 6) and
# MAGIC   `log_metrics` them into the same run.

# COMMAND ----------

from mlflow.genai.scorers import scorer
from mlflow.entities import Feedback

def _as_set(x):
    """Normalize a predicted/expected value to a set of code prefixes (e.g. '4B')."""
    if x is None:
        return set()
    if isinstance(x, dict):
        x = x.get("codes", [])
    return {str(c)[:2] for c in x}

@scorer
def jaccard(outputs, expectations) -> Feedback:
    """Set overlap with partial credit. Empty-vs-empty is a perfect 1.0."""
    pred, gold = _as_set(outputs), _as_set(expectations.get("expected_codes"))
    if not pred and not gold:
        val = 1.0
    else:
        val = len(pred & gold) / len(pred | gold)
    return Feedback(value=val, rationale=f"pred={sorted(pred)} gold={sorted(gold)}")

@scorer
def exact_match(outputs, expectations) -> Feedback:
    """Did we get the ENTIRE code set right? Brutal for multilabel — a sanity stat only."""
    pred, gold = _as_set(outputs), _as_set(expectations.get("expected_codes"))
    return Feedback(value=(pred == gold), rationale=f"pred={sorted(pred)} gold={sorted(gold)}")

@scorer
def abstained_correctly(outputs, expectations) -> Feedback:
    """The no-blocker lever: on rows that SHOULD be empty, did we assign nothing?
    Returns 'n/a' (not counted) on rows that should have a code."""
    pred, gold = _as_set(outputs), _as_set(expectations.get("expected_codes"))
    if gold:
        return Feedback(value="n/a", rationale="row has a true code; not an abstain case")
    return Feedback(value=(len(pred) == 0), rationale=f"should abstain; predicted {sorted(pred)}")

SCORERS = [jaccard, exact_match, abstained_correctly]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5 — Run `mlflow.genai.evaluate()` for this prompt variant
# MAGIC
# MAGIC `predict_fn` is a **pure lookup into the cache** — it does *no* LLM call (we paid
# MAGIC that cost once in Section 3). MLflow unpacks each row's `inputs` dict as keyword
# MAGIC arguments, so `predict_fn` takes `opportunity_id` and `transcript_text`. We apply
# MAGIC the confidence threshold here — a free precision/recall knob that touches no prompt.
# MAGIC
# MAGIC One `mlflow.start_run` = one prompt variant. The Experiments UI then shows every
# MAGIC variant side-by-side, reading like a changelog (`baseline_v1`, `v2_tighten_4B`, …).

# COMMAND ----------

# Load this config's cached predictions into a dict for O(1) lookup inside predict_fn.
_cache_rows = spark.sql(f"""
  SELECT opportunity_id, pred_codes, pred_confidences
  FROM {CACHE_TABLE} WHERE config_hash = '{CONFIG_HASH}'
""").collect()
_PREDS = {
    r["opportunity_id"]: list(zip(r["pred_codes"] or [], r["pred_confidences"] or []))
    for r in _cache_rows
}

@mlflow.trace  # predict_fn must emit exactly one trace per call
def predict_fn(opportunity_id: str, transcript_text: str) -> dict:
    # ai_classify returns the full label KEY (e.g. "4A. Rate/price uncompetitive").
    # Normalize to the "4A" prefix so predictions line up with the ground-truth codes.
    pairs = _PREDS.get(opportunity_id, [])
    codes = [c[:2] for (c, conf) in pairs if (conf is None or conf >= CONFIDENCE_THRESHOLD)]
    return {"codes": codes}

# Build the eval data in the shape MLflow wants: a list of {inputs, expectations} dicts.
# We control the expectations shape here so our scorers read `expected_codes` cleanly.
eval_data = [
    {
        "inputs": {"opportunity_id": r.opportunity_id, "transcript_text": r.transcript_text},
        "expectations": {"expected_codes": list(r.expected_codes or [])},
    }
    for r in gt.collect()
]
print(f"Prepared {len(eval_data)} evaluation records.")

# COMMAND ----------

with mlflow.start_run(run_name=RUN_LABEL) as run:
    # Log the FULL config so a run is self-describing and reproducible.
    mlflow.log_params({
        "config_hash": CONFIG_HASH,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "n_eval_rows": N_ROWS,
        "ai_version": AI_OPTIONS["version"],
        "multilabel": AI_OPTIONS["multilabel"],
    })
    mlflow.log_dict(PROMPT_CONFIG, "prompt_config.json")  # the exact prompt, as an artifact

    eval_result = mlflow.genai.evaluate(
        data=eval_data,
        predict_fn=predict_fn,
        scorers=SCORERS,
    )
    RUN_ID = run.info.run_id

print("Row-wise metrics from MLflow:")
for k, v in (eval_result.metrics or {}).items():
    print(f"  {k}: {v}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 6 — Corpus metrics + the read-the-noise panel
# MAGIC
# MAGIC Now the metrics that need the whole set at once. **Micro-F1 is the headline** — it
# MAGIC pools all 144 label decisions and is the steadiest number we have. **Macro-F1 is
# MAGIC reported with a warning** — it averages six per-class F1s, some with n≤4, so it
# MAGIC whiplashes. Per-label results are shown as **integer TP/FP/FN** because "3 of 4" is
# MAGIC honest and "0.75" hides the denominator.

# COMMAND ----------

# Build the per-row prediction/truth frame (apply the SAME threshold as predict_fn).
# Normalize predicted label keys to the "4A" prefix to match ground-truth codes.
pred_pd = pd.DataFrame(
    [{"opportunity_id": oid,
      "pred_set": {c[:2] for (c, conf) in pairs if (conf is None or conf >= CONFIDENCE_THRESHOLD)}}
     for oid, pairs in _PREDS.items()]
)
merged = gt_pd.merge(pred_pd, on="opportunity_id", how="left")
merged["pred_set"] = merged["pred_set"].apply(lambda s: s if isinstance(s, set) else set())

def prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1

# Per-label TP/FP/FN (one-vs-rest), then micro (pooled) and macro (averaged) F1.
per_label, micro = [], {"tp": 0, "fp": 0, "fn": 0}
for c in CODE_PREFIXES:
    tp = int(((merged["expected_set"].apply(lambda s: c in s)) & (merged["pred_set"].apply(lambda s: c in s))).sum())
    fp = int(((~merged["expected_set"].apply(lambda s: c in s)) & (merged["pred_set"].apply(lambda s: c in s))).sum())
    fn = int(((merged["expected_set"].apply(lambda s: c in s)) & (~merged["pred_set"].apply(lambda s: c in s))).sum())
    p, r, f1 = prf(tp, fp, fn)
    n_pos = tp + fn
    per_label.append({"code": c, "n_pos": n_pos, "TP": tp, "FP": fp, "FN": fn,
                      "precision": round(p, 2), "recall": round(r, 2), "f1": round(f1, 2),
                      "note": "⚠ n too small to trust" if n_pos <= 2 else ""})
    micro["tp"] += tp; micro["fp"] += fp; micro["fn"] += fn

per_label_df = pd.DataFrame(per_label)
micro_p, micro_r, micro_f1 = prf(micro["tp"], micro["fp"], micro["fn"])
# Macro EXCLUDES 4A (n=1): its F1 is a coin flip and would distort the average.
macro_codes = per_label_df[per_label_df["n_pos"] >= 2]
macro_f1 = float(macro_codes["f1"].mean()) if len(macro_codes) else 0.0

# Compute mean Jaccard directly (robust — don't depend on MLflow's aggregated metric key).
def _jac(p, g):
    if not p and not g:
        return 1.0
    return len(p & g) / len(p | g)
mean_jaccard = float(merged.apply(lambda r: _jac(r["pred_set"], r["expected_set"]), axis=1).mean())
abstain_rows = merged[merged["expected_set"].apply(len) == 0]
abstain_acc = float((abstain_rows["pred_set"].apply(len) == 0).mean()) if len(abstain_rows) else float("nan")

display(per_label_df)
print("\n================  HEADLINE (read fractions, not decimals)  ================")
print(f"  Micro-F1 (headline) : {micro_f1:.2f}   [pooled {micro['tp']}TP {micro['fp']}FP {micro['fn']}FN over 144 decisions]")
print(f"  Mean Jaccard        : {mean_jaccard:.2f}")
print(f"  Abstain accuracy    : {abstain_acc:.2f}   [{int((abstain_rows['pred_set'].apply(len)==0).sum())} of {len(abstain_rows)} empty rows correct]")
print(f"  Macro-F1 (⚠ noisy)  : {macro_f1:.2f}   [excludes 4A n=1; averages small classes]")
print("  Exact-match         : see MLflow run (sanity stat only — brutal for multilabel)")
print(f"\n  NOISE FLOOR: a single row flip ≈ ~{len(CODE_PREFIXES)/(N_ROWS*len(CODE_PREFIXES)):.0%} micro-F1."
      " Do NOT declare a winner on a sub-1-row move.")

# Log corpus metrics + the per-label table into the SAME run.
with mlflow.start_run(run_id=RUN_ID):
    mlflow.log_metrics({
        "micro_f1": micro_f1, "micro_precision": micro_p, "micro_recall": micro_r,
        "macro_f1_excl_4A": macro_f1, "mean_jaccard": mean_jaccard,
        "abstain_accuracy": abstain_acc,
    })
    mlflow.log_table(per_label_df, "per_label_metrics.json")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 7 — Error analysis: the main event
# MAGIC
# MAGIC This is where tuning decisions actually come from — **reading rationales one row at
# MAGIC a time**, not watching a number. We bucket every mistake, and because rationales are
# MAGIC ON we can usually name the root cause. We also keep an explicit lane for the
# MAGIC question newcomers forget at this scale: **"is the GOLD label actually right?"** —
# MAGIC at n=24 a mislabeled truth row is about as likely as a model error.

# COMMAND ----------

# Attach rationales/confidences for inspection.
_rat = spark.sql(f"""
  SELECT opportunity_id, pred_codes, pred_confidences, pred_rationales
  FROM {CACHE_TABLE} WHERE config_hash = '{CONFIG_HASH}'
""").toPandas()
err = merged.merge(_rat, on="opportunity_id", how="left")

def bucket(row):
    g, p = row["expected_set"], row["pred_set"]
    if g == p:
        return "correct"
    if not g and p:
        return "A. empty-class FALSE POSITIVE (assigned on a no-blocker call)"
    if g and not p:
        return "B. total MISS (true codes, predicted none)"
    if g - p and p - g:
        return "C. SUBSTITUTION (wrong code chosen — boundary error)"
    if p - g:
        return "D. EXTRA code (over-assigned alongside correct ones)"
    return "E. MISSED one of several codes"

err["bucket"] = err.apply(bucket, axis=1)
print("Error distribution (triage the biggest bucket first):")
print(err["bucket"].value_counts().to_string())

# COMMAND ----------

# Inspect the actual mistakes WITH their rationales. This drives every edit.
mistakes = err[err["bucket"] != "correct"][
    ["opportunity_id", "bucket", "expected_codes", "pred_codes", "pred_confidences", "pred_rationales"]
]
display(mistakes)

# COMMAND ----------

# MAGIC %md
# MAGIC ### The adjacent-code substitution matrix
# MAGIC
# MAGIC Multilabel has **no clean confusion matrix** (a row can be in several classes). What
# MAGIC *is* useful is a **substitution matrix**: when the model is wrong, which code did it
# MAGIC reach for instead? Hot cells on the 4A/4B/4C and 4C/4D boundaries point straight at
# MAGIC the **descriptions** that are leaking into each other.

# COMMAND ----------

import numpy as np
import matplotlib.pyplot as plt

labels_axis = CODE_PREFIXES + ["∅"]
idx = {c: i for i, c in enumerate(labels_axis)}
M = np.zeros((len(labels_axis), len(labels_axis)), dtype=int)
for _, row in err.iterrows():
    missed = row["expected_set"] - row["pred_set"]   # should have had, didn't
    added = row["pred_set"] - row["expected_set"]     # predicted, shouldn't have
    if not missed and added:          # pure false positive on an abstain row
        for a in added:
            M[idx["∅"], idx[a]] += 1
    elif missed and not added:        # pure miss
        for m in missed:
            M[idx[m], idx["∅"]] += 1
    else:                             # genuine swap: count every missed->added pair
        for m in missed:
            for a in added:
                M[idx[m], idx[a]] += 1

fig, ax = plt.subplots(figsize=(6, 5))
im = ax.imshow(M, cmap="Oranges")
ax.set_xticks(range(len(labels_axis))); ax.set_xticklabels(labels_axis)
ax.set_yticks(range(len(labels_axis))); ax.set_yticklabels(labels_axis)
ax.set_xlabel("predicted instead"); ax.set_ylabel("true code")
ax.set_title("Substitution matrix (true → predicted-instead)")
for i in range(len(labels_axis)):
    for j in range(len(labels_axis)):
        if M[i, j]:
            ax.text(j, i, M[i, j], ha="center", va="center")
fig.tight_layout()
display(fig)

with mlflow.start_run(run_id=RUN_ID):
    mlflow.log_figure(fig, "substitution_matrix.png")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 8 — Iteration decision guide: which surface do I edit?
# MAGIC
# MAGIC Match the **error signature** to the **lever**. Change **ONE surface per iteration**,
# MAGIC re-run, and diff the runs in the Experiments UI. Watch for whack-a-mole (a fix that
# MAGIC breaks another row).
# MAGIC
# MAGIC | Error signature (from Section 7) | Lever | How to use confidence to confirm |
# MAGIC |---|---|---|
# MAGIC | **Bucket C — substitution** (right evidence, wrong code; 4A/4B/4C or 4C/4D) | Edit the **DESCRIPTIONS** of *both* codes contrastively — add a discriminator and a "NOT this if…" clause to each side. Edit boundaries **in pairs**. | High-confidence wrong code ⇒ it's semantic; no threshold will fix it. |
# MAGIC | **Bucket A — empty-class false positive** (assigned on a no-blocker call) | Edit the **INSTRUCTIONS** (raise the evidence bar; reinforce "benchmarking-only ⇒ no code", "concern dissolved ⇒ no code"). This is your 50% class — biggest lever. | If FPs cluster at **low** confidence, the **threshold** fixes it cheaply instead. |
# MAGIC | **Bucket B/E — misses** (too timid) | Edit the **INSTRUCTIONS** (model is under-reading) or **lower the threshold**. | Rationale correct but code absent/low-confidence ⇒ threshold. |
# MAGIC | **Systematic over/under across all codes** | **CONFIDENCE THRESHOLD** first — it's free and touches no prompt. | Sweep it (next section) before editing any text. |
# MAGIC
# MAGIC > **Golden rule (print it on the wall):** *keep an edit only if it fixes a **class**
# MAGIC > of error for an articulable, generalizable reason — never because one row's number
# MAGIC > went up.* At n=24, one row moving is almost always noise.
# MAGIC >
# MAGIC > **To iterate:** duplicate the config cell in Section 0, change *one* surface, set a
# MAGIC > new `run_label` (e.g. `v2_tighten_4B_vs_4A`), and re-run from Section 0. The cache
# MAGIC > re-scores only this new config; everything else is instant.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 9 — Confidence-threshold sweep (the free lever)
# MAGIC
# MAGIC Because confidence scores are on, we have a precision/recall knob that costs nothing
# MAGIC and changes no prompt text. We sweep it over the **pooled** decisions (never
# MAGIC per-code — too sparse) and pick a **round, defensible** value, mostly driven by the
# MAGIC empty class. **Caveat:** foundation-model confidence is *not* calibrated probability
# MAGIC — treat τ as a tuned knob, not a real probability cut.

# COMMAND ----------

sweep_rows = []
for tau in [0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9]:
    tp = fp = fn = 0
    correct_abstain = total_abstain = 0
    for _, row in err.iterrows():
        pairs = list(zip(row["pred_codes_x"] if "pred_codes_x" in row else row["pred_codes"],
                         row["pred_confidences"]))
        pset = {c[:2] for (c, conf) in pairs if (conf is None or conf >= tau)}
        gset = row["expected_set"]
        tp += len(pset & gset); fp += len(pset - gset); fn += len(gset - pset)
        if not gset:
            total_abstain += 1
            correct_abstain += int(len(pset) == 0)
    _, _, f1 = prf(tp, fp, fn)
    sweep_rows.append({"tau": tau, "micro_f1": round(f1, 2),
                       "abstain_acc": round(correct_abstain / total_abstain, 2) if total_abstain else None})

sweep_df = pd.DataFrame(sweep_rows)
display(sweep_df)
print("Pick the SMALLEST τ that holds micro-F1 near its peak while improving abstain accuracy.")
print("Then set the `confidence_threshold` widget to that value and re-run — do NOT fit a false optimum on 24 rows.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 10 — Register the tuned prompt (handoff artifact)
# MAGIC
# MAGIC Once a variant is a defensible improvement, give "the answer" a durable, versioned
# MAGIC home in the **MLflow Prompt Registry**, decoupled from this notebook. We store the
# MAGIC labels+instructions as a single prompt template and tie it to the winning run.
# MAGIC Wrapped defensively so an older MLflow won't break the notebook.

# COMMAND ----------

PROMPT_NAME = f"{CATALOG}.{SCHEMA}.offer_blocker_ai_classify_prompt"
try:
    registered = mlflow.genai.register_prompt(
        name=PROMPT_NAME,
        template=json.dumps(PROMPT_CONFIG, ensure_ascii=False, indent=2),
        commit_message=f"{RUN_LABEL} (config_hash={CONFIG_HASH})",
    )
    print(f"✓ Registered {PROMPT_NAME} as version {registered.version}.")
    with mlflow.start_run(run_id=RUN_ID):
        mlflow.log_param("registered_prompt_version", registered.version)
except Exception as e:  # noqa: BLE001 - educational: never fail the notebook on an optional step
    print(f"(Skipped Prompt Registry: {type(e).__name__}: {e})")
    print("Prompt Registry needs a recent MLflow + Unity Catalog prompt support. "
          "The full config is still logged as prompt_config.json on the run.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 11 — The honest next steps (do not skip)
# MAGIC
# MAGIC ### Why we did NOT run automated prompt optimization (GEPA / `optimize_prompts`)
# MAGIC It is the right tool later and the wrong tool now:
# MAGIC * **No honest validation split.** A held-out from 24 rows is ~5 rows, and **4A's one
# MAGIC   example cannot be in both train and validation** — class-level signal is impossible.
# MAGIC * **Its signal is the metric, and the metric is noise here.** GEPA would happily
# MAGIC   memorize these 24 transcripts (learning the labels, not the task) with no
# MAGIC   instrument able to detect the lost generalization.
# MAGIC * **It removes the rationale-reading that is the actual value at this scale** and
# MAGIC   emits opaque evolved text a newcomer can't reason about.
# MAGIC
# MAGIC When your set reaches a few hundred rows with a real held-out split, this is the call
# MAGIC (shown, intentionally **not executed**):
# MAGIC ```python
# MAGIC # from mlflow.genai import optimize_prompts   # requires mlflow >= 3.5.0
# MAGIC # optimize_prompts(predict_fn=..., train_data=..., eval_data=held_out, scorers=[...])
# MAGIC ```
# MAGIC
# MAGIC ### Your real #1 priority: grow and curate the labeled set
# MAGIC Your eval-set size sets the **ceiling** on how much you can trust *any* result —
# MAGIC manual or automated. Today's ceiling and what unlocks the next tier:
# MAGIC
# MAGIC | Code | Now | Target (min usable) |
# MAGIC |---|---|---|
# MAGIC | empty / no-blocker | 12 | keep ~40–50% of total |
# MAGIC | 4A | **1** | ~10 |
# MAGIC | 4B–4D | 4 each | ~10–15 each |
# MAGIC | 4E–4F | 3 each | ~10–15 each |
# MAGIC | **total** | **24** | **~150–300** |
# MAGIC
# MAGIC The managed dataset makes growth cheap: **append rows, re-run this same notebook,
# MAGIC same scorers.** And **audit label quality** — double-label a subset for
# MAGIC inter-annotator agreement and re-adjudicate every disagreement your rationales
# MAGIC surface. Reading a clearly-correct model rationale against a clearly-wrong gold label
# MAGIC is one of the highest-value things that happens in this loop.
# MAGIC
# MAGIC ### Measure model stochasticity (optional, cheap here)
# MAGIC `ai_classify` is non-deterministic. To show the customer the *second* noise floor,
# MAGIC re-run one config 3–5× under different `run_label`s with the cache cleared for that
# MAGIC hash, and watch micro-F1 wobble with the prompt held fixed.
# MAGIC
# MAGIC ### When you promote a tuned prompt to the pipeline
# MAGIC Copy the winning `LABELS` + `INSTRUCTIONS` back into
# MAGIC `pipeline/transformations/gold/gold_opportunity_enrichment.sql`. Because this
# MAGIC notebook builds its `ai_classify` SQL from the same two surfaces, what you evaluated
# MAGIC is exactly what the pipeline will run.
