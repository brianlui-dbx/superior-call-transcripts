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
# MAGIC `ai_classify` call — using MLflow as the scaffolding.
# MAGIC
# MAGIC ## What are we evaluating?
# MAGIC `gold_opportunity_enrichment` runs **one** `ai_classify(...)` per sales-call
# MAGIC transcript. It is **multilabel**: a transcript can receive 0..N "offer-blocker"
# MAGIC codes (**4A–4F**). The foundation model is fixed — the thing we actually tune is a
# MAGIC **prompt**, and that prompt lives in **two surfaces**:
# MAGIC
# MAGIC 1. the six **label descriptions** (the routing rules per code), and
# MAGIC 2. the global **instructions** string (when to assign *anything* at all).
# MAGIC
# MAGIC > **The one mental model to internalize:** *we are not evaluating a model, we are
# MAGIC > evaluating a prompt.* A "model version" here **is** a `(descriptions +
# MAGIC > instructions + options)` bundle. Evaluation is a function
# MAGIC > `prompt_config → accuracy metrics`.
# MAGIC
# MAGIC ## How this notebook is organized
# MAGIC
# MAGIC | Phase | Sections | What happens |
# MAGIC |-------|----------|--------------|
# MAGIC | **Setup** | 0–1 | Parameters, prompt config, **register prompt in Prompt Registry** |
# MAGIC | **Data** | 2–3 | Load managed eval dataset, inspect class balance, train/validation/test split |
# MAGIC | **Score** | 4–7 | Build SQL, cache predictions, run `mlflow.genai.evaluate()`, corpus metrics |
# MAGIC | **Diagnose** | 8–10 | Error analysis, substitution matrix, decision guide + threshold sweep |
# MAGIC | **Compare** | 11 | Programmatic side-by-side of all runs |
# MAGIC | **Optimize** | 12–13 | (Optional) GEPA automated prompt optimization (3-way split) + conditional promotion |
# MAGIC | **Ship** | 14 | Next steps: pipeline integration, production monitoring |
# MAGIC
# MAGIC The notebook is **idempotent**: run it top-to-bottom any number of times and you
# MAGIC get the same experiment state. Expensive `ai_classify` calls are cached by a
# MAGIC hash of the prompt config, so re-runs are free *and* deterministic.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 0 — Setup & parameters

# COMMAND ----------

# MAGIC %pip install -q -U "mlflow[databricks]>=3.5"
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
dbutils.widgets.dropdown("run_gepa", "false", ["false", "true"], "Run GEPA automated optimization?")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
EVAL_TABLE = f"{CATALOG}.{SCHEMA}.{dbutils.widgets.get('eval_table')}"
CACHE_TABLE = f"{CATALOG}.{SCHEMA}.ai_classify_eval_cache"
PROMPT_NAME = f"{CATALOG}.{SCHEMA}.offer_blocker_ai_classify_prompt"
RUN_LABEL = dbutils.widgets.get("run_label")
CONFIDENCE_THRESHOLD = float(dbutils.widgets.get("confidence_threshold"))
RUN_GEPA = dbutils.widgets.get("run_gepa") == "true"

print(f"Ground truth : {EVAL_TABLE}")
print(f"Cache table  : {CACHE_TABLE}")
print(f"Prompt name  : {PROMPT_NAME}")
print(f"Run label    : {RUN_LABEL}")
print(f"Confidence τ : {CONFIDENCE_THRESHOLD}")
print(f"Run GEPA     : {RUN_GEPA}")

# COMMAND ----------

import json
import hashlib
import mlflow

# Point MLflow at an experiment. Blank => the notebook's own default experiment.
_exp = dbutils.widgets.get("experiment_path").strip()
if _exp:
    mlflow.set_experiment(_exp)
    print(f"Using experiment: {_exp}")
else:
    print("Using the notebook's default experiment (no path set).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1 — The prompt config & the Prompt Registry
# MAGIC
# MAGIC **Best practice: your prompt is a *versioned artifact*, not a string in a code
# MAGIC cell.** We define the two tunable surfaces here, bundle them into one config, and
# MAGIC register that config in the **MLflow Prompt Registry** — a Unity-Catalog-backed
# MAGIC version store for prompt templates.
# MAGIC
# MAGIC The iteration loop becomes:
# MAGIC 1. **Edit** one surface below (descriptions *or* instructions — never both at once).
# MAGIC 2. **Register** a new prompt version (the cell below does this automatically).
# MAGIC 3. **Evaluate** by re-running the notebook with a new `run_label`.
# MAGIC 4. **Compare** runs side-by-side in the Experiments UI.
# MAGIC 5. **Promote** the winner to the `"production"` alias (Section 13).
# MAGIC
# MAGIC > Keep the baseline below **byte-for-byte identical to production** so your first
# MAGIC > number reflects reality.

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

# The ordered list of valid code prefixes. Order is held FIXED across variants so we
# measure the description text, not a label-ordering artifact.
CODE_PREFIXES = ["4A", "4B", "4C", "4D", "4E", "4F"]

# COMMAND ----------

# Bundle the two surfaces + options into one config and hash it. The hash is the cache
# key and the thing we log to MLflow — so every result is traceable to the exact prompt.
PROMPT_CONFIG = {"labels": LABELS, "instructions": INSTRUCTIONS, "options": AI_OPTIONS}
_config_blob = json.dumps(PROMPT_CONFIG, sort_keys=True, ensure_ascii=False)
CONFIG_HASH = hashlib.sha256(_config_blob.encode("utf-8")).hexdigest()[:16]
print(f"CONFIG_HASH = {CONFIG_HASH}  (changes whenever ANY surface changes)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Register the config in the Prompt Registry
# MAGIC
# MAGIC Each prompt variant becomes a **version** in the registry. The notebook checks
# MAGIC whether the latest version already matches (idempotency) — if so, it reuses it
# MAGIC rather than creating a duplicate.

# COMMAND ----------

def _register_if_changed(name, template, commit_message):
    """Register a new prompt version only if the content has changed."""
    try:
        latest = mlflow.genai.load_prompt(f"prompts:/{name}")
        if latest.template.strip() == template.strip():
            print(f"✓ Prompt '{name}' v{latest.version} already matches — reusing.")
            return latest
    except Exception:
        pass  # Prompt doesn't exist yet
    registered = mlflow.genai.register_prompt(
        name=name,
        template=template,
        commit_message=commit_message,
    )
    print(f"✓ Registered '{name}' as v{registered.version}: {commit_message}")
    return registered

_config_template = json.dumps(PROMPT_CONFIG, ensure_ascii=False, indent=2)

try:
    PROMPT_VERSION = _register_if_changed(
        name=PROMPT_NAME,
        template=_config_template,
        commit_message=f"{RUN_LABEL} (config_hash={CONFIG_HASH})",
    )
except Exception as e:
    # Prompt Registry may not be available in all workspaces/MLflow versions.
    PROMPT_VERSION = None
    print(f"(Prompt Registry unavailable: {type(e).__name__}: {e})")
    print("Continuing without it — the config is still hashed and logged as a run artifact.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2 — Load the ground truth
# MAGIC
# MAGIC The eval table is an **MLflow managed evaluation dataset** — a Unity Catalog table
# MAGIC with `inputs` and `expectations` JSON columns. We load it via the MLflow managed
# MAGIC dataset API (with a Spark fallback), then parse the JSON into a clean shape.
# MAGIC
# MAGIC **Best practice: inspect the data before you measure anything.** The class balance
# MAGIC table sets your expectations for *every* number below.

# COMMAND ----------

import pandas as pd
from pyspark.sql import functions as F

# --- Load the table (try managed-dataset API first, fall back to Spark) ---------------
try:
    import mlflow.genai.datasets
    _ds = mlflow.genai.datasets.get_dataset(EVAL_TABLE)
    _raw_pd = _ds.to_df()
    print(f"✓ Loaded via mlflow.genai.datasets.get_dataset (managed dataset API)")
except Exception:
    _raw_pd = spark.table(EVAL_TABLE).toPandas()
    print(f"✓ Loaded via spark.table() (fallback)")

# --- Parse JSON columns → clean Python types ------------------------------------------
def _parse_row(row):
    inputs = json.loads(row["inputs"]) if isinstance(row["inputs"], str) else row["inputs"]
    exp_raw = json.loads(row["expectations"]) if isinstance(row["expectations"], str) else row["expectations"]
    # expected_response is a JSON-stringified array, e.g. '["4B","4C"]' or '[]'
    expected_codes = json.loads(exp_raw.get("expected_response", "[]"))
    return {
        "opportunity_id": inputs["opportunity_id"],
        "transcript_text": inputs["transcript_text"],
        "expected_codes": expected_codes,
        "expected_set": set(expected_codes),
    }

gt_pd = pd.DataFrame([_parse_row(r) for _, r in _raw_pd.iterrows()])
N_ROWS = len(gt_pd)
print(f"Parsed {N_ROWS} ground-truth rows.")
display(gt_pd[["opportunity_id", "expected_codes"]].head(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Class balance — the single most important table in this notebook

# COMMAND ----------

n_empty = int((gt_pd["expected_set"].apply(len) == 0).sum())
balance = pd.DataFrame(
    {"code": CODE_PREFIXES,
     "positive_rows": [int(gt_pd["expected_set"].apply(lambda s: c in s).sum()) for c in CODE_PREFIXES]}
)
pooled = N_ROWS * len(CODE_PREFIXES)

print(f"Total rows            : {N_ROWS}")
print(f"Empty / no-blocker    : {n_empty}  ({n_empty / N_ROWS:.0%})")
print(f"Pooled label decisions: {pooled}  <- the REAL sample size for micro-F1")
display(balance)

# Dynamic noise floor — works at any n
print(
    "\n⚠️  NOISE FLOOR (read this before any metric):\n"
    f"   • 1 flipped label ≈ {1 / pooled:.1%} of micro decisions\n"
    f"   • 1 flipped ROW   ≈ ~{len(CODE_PREFIXES) / pooled:.1%} swing in micro-F1\n"
    f"   Treat metric moves smaller than ~1 row as NOISE, not progress."
)
for _, r in balance.iterrows():
    if r["positive_rows"] <= 2:
        print(f"   ⚠  {r['code']} has only {r['positive_rows']} positive(s) — its per-label F1 is a coin flip.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3 — Train / validation / test split (3-way)
# MAGIC
# MAGIC When running automated prompt optimization (GEPA, Section 12), we need **two**
# MAGIC held-out splits — not just one:
# MAGIC
# MAGIC | Split | Purpose | Who sees it |
# MAGIC |-------|---------|-------------|
# MAGIC | **Train** (~70%) | What GEPA optimizes against | GEPA |
# MAGIC | **Validation** (~15%) | Picks the winning prompt among GEPA candidates | GEPA (for selection, so it's "used up") |
# MAGIC | **Test** (~15%) | Final honest check — truly untouched | **Nobody until final eval** |
# MAGIC
# MAGIC **Why 3 splits, not 2?** The validation set is compromised by *selection*:
# MAGIC repeatedly choosing the prompt that scores best on it can overfit to that set, even
# MAGIC though GEPA didn't directly train on it. The test set is the only truly independent
# MAGIC assessment. Think of it as "train is for learning, validation is for choosing, test
# MAGIC is for believing."
# MAGIC
# MAGIC For **manual tuning** (the primary loop), you still evaluate on the **full** dataset
# MAGIC — you're making generalizable edits informed by rationales, not fitting to data.
# MAGIC
# MAGIC The split is **deterministic** (hash-based, seeded) so it is reproducible across
# MAGIC re-runs. We validate that every label appears in all three splits.

# COMMAND ----------

SPLIT_SEED = 42
VALIDATION_FRACTION = 0.15  # 15% held out for GEPA selection ("used up" by choosing)
TEST_FRACTION = 0.15        # 15% held out for final honest eval (never seen by GEPA)
# Remaining ~70% is the train split.

def _split_hash(opportunity_id, seed=SPLIT_SEED):
    """Deterministic assignment: 0.0–1.0 from a hash of (seed, id)."""
    h = hashlib.md5(f"{seed}:{opportunity_id}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF

def _assign_split(h):
    if h < TEST_FRACTION:
        return "test"
    elif h < TEST_FRACTION + VALIDATION_FRACTION:
        return "validation"
    else:
        return "train"

gt_pd["_split_val"] = gt_pd["opportunity_id"].apply(_split_hash)
gt_pd["split"] = gt_pd["_split_val"].apply(_assign_split)

train_pd = gt_pd[gt_pd["split"] == "train"].copy()
validation_pd = gt_pd[gt_pd["split"] == "validation"].copy()
test_pd = gt_pd[gt_pd["split"] == "test"].copy()

print(f"Train: {len(train_pd)} rows | Validation: {len(validation_pd)} rows | Test (untouched): {len(test_pd)} rows")
print(f"  Train     → GEPA optimizes against this")
print(f"  Validation→ GEPA selects the best prompt candidate using this")
print(f"  Test      → final honest eval AFTER GEPA finishes (never seen during optimization)")

# Validate label coverage in all three splits
for split_name, split_df in [("train", train_pd), ("validation", validation_pd), ("test", test_pd)]:
    present = {c for c in CODE_PREFIXES if split_df["expected_set"].apply(lambda s: c in s).any()}
    missing = set(CODE_PREFIXES) - present
    if missing:
        print(f"  ⚠ {split_name} split is missing labels: {sorted(missing)}  "
              f"(consider adjusting SPLIT_SEED or adding more ground-truth rows)")
    else:
        print(f"  ✓ {split_name} split covers all {len(CODE_PREFIXES)} labels")

# At small n, warn about split viability
min_split = min(len(train_pd), len(validation_pd), len(test_pd))
if min_split < 10:
    print(f"\n  ⚠ SMALLEST SPLIT HAS ONLY {min_split} ROWS. The 3-way split is meaningful")
    print(f"    only once total n ≥ ~100. At current n={N_ROWS}, GEPA results will be noisy.")
    print(f"    Manual tuning (which evaluates on the FULL dataset) is more reliable for now.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4 — Build the `ai_classify` SQL & reproducibility cache
# MAGIC
# MAGIC We turn the Python config into the exact `ai_classify(...)` SQL the pipeline runs,
# MAGIC then cache the LLM results in a Delta table keyed by `config_hash`. Same config →
# MAGIC same predictions → same metrics, forever. The cache is also the audit trail.

# COMMAND ----------

def _sql_str(s):
    """Safely embed a Python string as a SQL string literal."""
    return "'" + s.replace("'", "''") + "'"

def build_ai_classify_expr(column, config):
    """Render the ai_classify(...) SQL expression for a given prompt config."""
    labels_json = json.dumps(config["labels"], ensure_ascii=False)
    opts = dict(config["options"])
    opts["instructions"] = config["instructions"]
    opt_pairs = ", ".join(f"{_sql_str(k)}, {_sql_str(v)}" for k, v in opts.items())
    return f"ai_classify({column}, {_sql_str(labels_json)}, map({opt_pairs}))"

print(build_ai_classify_expr("transcript_text", PROMPT_CONFIG)[:600], "...")

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

def classify_and_cache(config, config_hash):
    """Run ai_classify and persist results. Idempotent: skips if already cached."""
    have = spark.sql(
        f"SELECT COUNT(*) AS n FROM {CACHE_TABLE} WHERE config_hash = '{config_hash}'"
    ).collect()[0]["n"]
    if have >= N_ROWS:
        print(f"✓ config {config_hash} already cached ({have} rows) — skipping LLM calls.")
        return

    print(f"Running ai_classify for config {config_hash} over {N_ROWS} rows …")
    _gt_spark = spark.createDataFrame(gt_pd[["opportunity_id", "transcript_text"]])
    _gt_spark.createOrReplaceTempView("_eval_inputs")
    expr = build_ai_classify_expr("transcript_text", config)

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

    scored.createOrReplaceTempView("_scored")
    spark.sql(f"DELETE FROM {CACHE_TABLE} WHERE config_hash = '{config_hash}'")
    spark.sql(f"INSERT INTO {CACHE_TABLE} SELECT * FROM _scored")
    print(f"✓ cached {scored.count()} predictions for config {config_hash}.")

classify_and_cache(PROMPT_CONFIG, CONFIG_HASH)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5 — Deterministic scorers
# MAGIC
# MAGIC We have ground truth → compare sets with plain Python. **No LLM judge is needed.**
# MAGIC
# MAGIC Two kinds of measurement (knowing which is which is a core lesson):
# MAGIC * **Row-wise** (Jaccard, exact-match, abstain, per-label hits) — MLflow `@scorer`
# MAGIC   functions; visible per-row in the Trace UI.
# MAGIC * **Corpus-wide** (precision / recall / F1) — need the whole set at once; computed
# MAGIC   in Section 7 and `log_metrics`'d into the same run.

# COMMAND ----------

from mlflow.genai.scorers import scorer
from mlflow.entities import Feedback

def _as_set(x):
    """Normalize a predicted/expected value to a set of code prefixes (e.g. '4B')."""
    if x is None:
        return set()
    if isinstance(x, dict):
        x = x.get("codes", [])
    if isinstance(x, str):
        x = json.loads(x) if x.startswith("[") else [x]
    return {str(c)[:2] for c in (x or [])}


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
    """Entire code set right? Brutal for multilabel — a sanity stat only."""
    pred, gold = _as_set(outputs), _as_set(expectations.get("expected_codes"))
    return Feedback(value=(pred == gold), rationale=f"pred={sorted(pred)} gold={sorted(gold)}")


@scorer
def abstained_correctly(outputs, expectations) -> Feedback:
    """On rows that SHOULD be empty, did we assign nothing?
    Returns 'n/a' on rows that should have a code."""
    pred, gold = _as_set(outputs), _as_set(expectations.get("expected_codes"))
    if gold:
        return Feedback(value="n/a", rationale="row has a true code; not an abstain case")
    return Feedback(value=(len(pred) == 0), rationale=f"should abstain; predicted {sorted(pred)}")


@scorer
def per_label_hits(outputs, expectations):
    """Per-label TP/FP/FN as individual Feedback objects. Shows per-row, per-code
    correctness in the MLflow Trace UI — much richer than a single aggregate."""
    pred, gold = _as_set(outputs), _as_set(expectations.get("expected_codes"))
    feedbacks = []
    for c in ["4A", "4B", "4C", "4D", "4E", "4F"]:
        in_pred, in_gold = c in pred, c in gold
        if in_gold and in_pred:
            tag = "TP"
        elif in_gold and not in_pred:
            tag = "FN"
        elif not in_gold and in_pred:
            tag = "FP"
        else:
            tag = "TN"
        feedbacks.append(Feedback(
            name=f"label_{c}",
            value=(tag in ("TP", "TN")),
            rationale=tag,
        ))
    return feedbacks


SCORERS = [jaccard, exact_match, abstained_correctly, per_label_hits]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 6 — Run `mlflow.genai.evaluate()`
# MAGIC
# MAGIC `predict_fn` is a **pure lookup into the cache** — no LLM call. MLflow unpacks
# MAGIC each row's `inputs` dict as keyword arguments, so `predict_fn(opportunity_id=...,
# MAGIC transcript_text=...)`. One `mlflow.start_run` = one prompt variant; the Experiments
# MAGIC UI then shows them side-by-side.

# COMMAND ----------

# Load cached predictions into a dict for O(1) lookup inside predict_fn.
_cache_rows = spark.sql(f"""
  SELECT opportunity_id, pred_codes, pred_confidences, pred_rationales
  FROM {CACHE_TABLE} WHERE config_hash = '{CONFIG_HASH}'
""").collect()

_PREDS = {
    r["opportunity_id"]: list(zip(r["pred_codes"] or [], r["pred_confidences"] or []))
    for r in _cache_rows
}
_RATS = {
    r["opportunity_id"]: (r["pred_rationales"] or [])
    for r in _cache_rows
}


@mlflow.trace
def predict_fn(opportunity_id, transcript_text):
    """Pure cache lookup — applies confidence threshold, normalizes label prefixes."""
    pairs = _PREDS.get(opportunity_id, [])
    codes = [c[:2] for (c, conf) in pairs if (conf is None or conf >= CONFIDENCE_THRESHOLD)]
    confidences = [conf for (c, conf) in pairs if (conf is None or conf >= CONFIDENCE_THRESHOLD)]
    rationales = _RATS.get(opportunity_id, [])
    return {"codes": codes, "confidences": confidences, "rationales": rationales}


# Build eval data in the shape MLflow expects: a list of {inputs, expectations} dicts.
eval_data = [
    {
        "inputs": {"opportunity_id": r.opportunity_id, "transcript_text": r.transcript_text},
        "expectations": {"expected_codes": list(r.expected_codes)},
    }
    for _, r in gt_pd.iterrows()
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
    if PROMPT_VERSION:
        mlflow.log_params({
            "prompt_registry_name": PROMPT_NAME,
            "prompt_registry_version": PROMPT_VERSION.version,
        })
    mlflow.log_dict(PROMPT_CONFIG, "prompt_config.json")

    eval_result = mlflow.genai.evaluate(
        data=eval_data,
        predict_fn=predict_fn,
        scorers=SCORERS,
    )
    RUN_ID = run.info.run_id

print(f"\nRun ID: {RUN_ID}")
print("Row-wise metrics from MLflow:")
for k, v in sorted((eval_result.metrics or {}).items()):
    print(f"  {k}: {v}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 7 — Corpus metrics + the noise panel
# MAGIC
# MAGIC Now the metrics that need the whole set at once. **Micro-F1 is the headline** — it
# MAGIC pools all `n × 6` label decisions and is the steadiest number. **Macro-F1** averages
# MAGIC per-label F1s (some with tiny n) so it whiplashes — report it with a warning.
# MAGIC Per-label results are shown as **integer TP/FP/FN** because "3 of 4" is honest and
# MAGIC "0.75" hides the denominator.

# COMMAND ----------

import numpy as np

# Build per-row prediction/truth frame (apply SAME threshold as predict_fn).
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


# Per-label TP/FP/FN, then micro (pooled) and macro (averaged) F1.
per_label, micro = [], {"tp": 0, "fp": 0, "fn": 0}
for c in CODE_PREFIXES:
    tp = int(((merged["expected_set"].apply(lambda s: c in s)) & (merged["pred_set"].apply(lambda s: c in s))).sum())
    fp = int(((~merged["expected_set"].apply(lambda s: c in s)) & (merged["pred_set"].apply(lambda s: c in s))).sum())
    fn = int(((merged["expected_set"].apply(lambda s: c in s)) & (~merged["pred_set"].apply(lambda s: c in s))).sum())
    p, r, f1 = prf(tp, fp, fn)
    n_pos = tp + fn
    per_label.append({"code": c, "n_pos": n_pos, "TP": tp, "FP": fp, "FN": fn,
                      "precision": round(p, 2), "recall": round(r, 2), "f1": round(f1, 2),
                      "note": "⚠ n too small" if n_pos <= 2 else ""})
    micro["tp"] += tp; micro["fp"] += fp; micro["fn"] += fn

per_label_df = pd.DataFrame(per_label)
micro_p, micro_r, micro_f1 = prf(micro["tp"], micro["fp"], micro["fn"])

# Macro EXCLUDES codes with n_pos ≤ 2 (their F1 is noise, not signal).
macro_codes = per_label_df[per_label_df["n_pos"] > 2]
macro_f1 = float(macro_codes["f1"].mean()) if len(macro_codes) else 0.0

# Mean Jaccard (robust, computed directly).
def _jac(p, g):
    if not p and not g:
        return 1.0
    return len(p & g) / len(p | g)
mean_jaccard = float(merged.apply(lambda r: _jac(r["pred_set"], r["expected_set"]), axis=1).mean())

# Abstain accuracy (the 50%-class lever).
abstain_rows = merged[merged["expected_set"].apply(len) == 0]
abstain_acc = float((abstain_rows["pred_set"].apply(len) == 0).mean()) if len(abstain_rows) else float("nan")

display(per_label_df)
excluded_labels = set(per_label_df[per_label_df["n_pos"] <= 2]["code"])
excl_note = f" [excludes {sorted(excluded_labels)} n≤2]" if excluded_labels else ""

print("\n================  HEADLINE  ================")
print(f"  Micro-F1 (headline) : {micro_f1:.2f}   [pooled {micro['tp']}TP {micro['fp']}FP {micro['fn']}FN over {pooled} decisions]")
print(f"  Mean Jaccard        : {mean_jaccard:.2f}")
print(f"  Abstain accuracy    : {abstain_acc:.2f}   [{int((abstain_rows['pred_set'].apply(len)==0).sum())} of {len(abstain_rows)} empty rows correct]")
print(f"  Macro-F1 (⚠ noisy)  : {macro_f1:.2f}  {excl_note}")
print(f"  Exact-match         : see MLflow run (sanity stat only — brutal for multilabel)")
print(f"\n  NOISE FLOOR: 1 row flip ≈ ~{len(CODE_PREFIXES)/pooled:.0%} micro-F1."
      " Do NOT declare a winner on a sub-1-row move.")

# Log corpus metrics into the SAME run.
with mlflow.start_run(run_id=RUN_ID):
    mlflow.log_metrics({
        "micro_f1": micro_f1, "micro_precision": micro_p, "micro_recall": micro_r,
        "macro_f1": macro_f1, "mean_jaccard": mean_jaccard, "abstain_accuracy": abstain_acc,
    })
    mlflow.log_table(per_label_df, "per_label_metrics.json")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 8 — Error analysis: the main event
# MAGIC
# MAGIC This is where tuning decisions actually come from — **reading rationales one row at
# MAGIC a time**, not watching a number. We bucket every mistake, and because rationales are
# MAGIC ON we can usually name the root cause. We also keep an explicit lane for a question
# MAGIC newcomers forget: **"is the GOLD label actually right?"** — a mislabeled truth row
# MAGIC is just as damaging as a model error.

# COMMAND ----------

# Attach rationales and confidences for inspection.
_rat_pd = spark.sql(f"""
  SELECT opportunity_id, pred_codes, pred_confidences, pred_rationales
  FROM {CACHE_TABLE} WHERE config_hash = '{CONFIG_HASH}'
""").toPandas()
err = merged.merge(_rat_pd, on="opportunity_id", how="left", suffixes=("", "_cache"))

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
# MAGIC ## Section 9 — Substitution matrix
# MAGIC
# MAGIC Multilabel has **no clean confusion matrix**. What *is* useful is a **substitution
# MAGIC matrix**: when the model is wrong, which code did it reach for instead? Hot cells on
# MAGIC the 4A/4B/4C and 4C/4D boundaries point straight at the descriptions that leak.

# COMMAND ----------

import matplotlib.pyplot as plt

labels_axis = CODE_PREFIXES + ["∅"]
idx = {c: i for i, c in enumerate(labels_axis)}
M = np.zeros((len(labels_axis), len(labels_axis)), dtype=int)
for _, row in err.iterrows():
    missed = row["expected_set"] - row["pred_set"]
    added = row["pred_set"] - row["expected_set"]
    if not missed and added:
        for a in added:
            M[idx["∅"], idx[a]] += 1
    elif missed and not added:
        for m in missed:
            M[idx[m], idx["∅"]] += 1
    else:
        for m in missed:
            for a in added:
                M[idx[m], idx[a]] += 1

fig, ax = plt.subplots(figsize=(6, 5))
ax.imshow(M, cmap="Oranges")
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
# MAGIC ## Section 10 — Iteration decision guide + confidence-threshold sweep
# MAGIC
# MAGIC ### Which surface do I edit?
# MAGIC
# MAGIC Match the **error signature** (from Section 8) to the **lever**. Change **ONE
# MAGIC surface per iteration**, re-run, and diff the runs.
# MAGIC
# MAGIC | Error signature | Lever | Confidence tells you… |
# MAGIC |---|---|---|
# MAGIC | **C: Substitution** (right evidence, wrong code) | Edit **DESCRIPTIONS** of *both* codes contrastively — in pairs. | High-confidence wrong code ⇒ semantic; no threshold will fix it. |
# MAGIC | **A: Empty-class FP** (assigned on a no-blocker call) | Edit **INSTRUCTIONS** (raise evidence bar). This is your biggest lever. | Low-confidence FPs ⇒ **threshold** fixes it cheaply. |
# MAGIC | **B/E: Misses** (too timid) | Edit **INSTRUCTIONS** or **lower threshold**. | Rationale correct but code absent ⇒ threshold. |
# MAGIC | **Systematic across all codes** | **CONFIDENCE THRESHOLD** first — it's free. | Sweep below to find the right τ. |
# MAGIC
# MAGIC > **Golden rule:** *keep an edit only if it fixes a **class** of error for an
# MAGIC > articulable reason — never because one row's number went up.*
# MAGIC
# MAGIC ### To iterate
# MAGIC 1. Duplicate the config cell in Section 1.
# MAGIC 2. Edit **one** surface.
# MAGIC 3. Set a new `run_label` (e.g. `v2_tighten_4B_vs_4A`).
# MAGIC 4. Re-run from Section 0. Only the new config re-scores; everything else is instant.
# MAGIC 5. Compare runs in the Experiments UI (or Section 11 below).

# COMMAND ----------

# MAGIC %md
# MAGIC ### Confidence-threshold sweep (the free lever)
# MAGIC
# MAGIC Because confidence scores are on, we have a precision/recall knob that costs nothing
# MAGIC and changes no prompt text. **Caveat:** foundation-model confidence is *not*
# MAGIC calibrated probability — treat τ as a tuned knob, not a real probability cut.

# COMMAND ----------

sweep_rows = []
for tau in [0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9]:
    tp = fp = fn = 0
    correct_abstain = total_abstain = 0
    for _, row in err.iterrows():
        raw_codes = row.get("pred_codes_cache") or row.get("pred_codes") or []
        raw_confs = row.get("pred_confidences_cache") or row.get("pred_confidences") or []
        pairs = list(zip(raw_codes, raw_confs))
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
print("Then set the `confidence_threshold` widget to that value and re-run.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 11 — Programmatic run comparison
# MAGIC
# MAGIC Once you have 2+ prompt variants evaluated, compare them side-by-side. This code
# MAGIC reads all runs in the current experiment and builds a comparison table. The same
# MAGIC view is available in the MLflow Experiments UI (Metrics tab → Compare), but this
# MAGIC gives you programmatic access for downstream decisions.

# COMMAND ----------

_all_runs = mlflow.search_runs(order_by=["start_time DESC"])
if len(_all_runs) > 0:
    _metric_cols = [c for c in _all_runs.columns if c.startswith("metrics.")]
    _param_cols = ["params.run_label", "params.config_hash", "params.confidence_threshold",
                   "params.prompt_registry_version", "params.n_eval_rows"]
    _keep = ["run_id"] + [c for c in _param_cols if c in _all_runs.columns] + sorted(_metric_cols)
    comparison_df = _all_runs[[c for c in _keep if c in _all_runs.columns]].head(20)
    display(comparison_df)
    print(f"Showing the {len(comparison_df)} most recent runs. Use the Experiments UI for "
          "interactive comparison, drill-down into traces, and side-by-side metrics charts.")
else:
    print("No runs found — this is the first evaluation. Run again with a different "
          "run_label after editing the config to see a comparison.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 12 — (Optional) GEPA automated prompt optimization
# MAGIC
# MAGIC **`optimize_prompts()`** uses the Genetic-Pareto (GEPA) optimizer to automatically
# MAGIC evolve your prompt text. It is powerful but dangerous:
# MAGIC
# MAGIC * It uses a **3-way split** (Section 3): train for optimization, validation for
# MAGIC   selecting the best candidate, and test for the final honest check.
# MAGIC * It **optimizes the INSTRUCTIONS only** — descriptions are the structured routing
# MAGIC   rules and should be edited manually (GEPA would break their contrastive structure).
# MAGIC * Each GEPA iteration calls `ai_classify` per-row via SQL — this is **slow and
# MAGIC   costly** (train_size × max_metric_calls × per_call_cost). Budget accordingly.
# MAGIC
# MAGIC **When to use this:** once your eval set has ~200+ total rows (~30+ per label per
# MAGIC split) and manual tuning has plateaued. **When NOT to use this:** small eval sets,
# MAGIC or when the errors are in label *boundaries* (those need contrastive description
# MAGIC edits, not instruction rewrites).
# MAGIC
# MAGIC > Set the `run_gepa` widget to `true` to enable this section.

# COMMAND ----------

if RUN_GEPA:
    from mlflow.genai.optimize import GepaPromptOptimizer

    # Register the INSTRUCTIONS as a separate, optimizable prompt.
    # GEPA evolves this text; descriptions stay fixed.
    INSTRUCTIONS_PROMPT_NAME = f"{CATALOG}.{SCHEMA}.offer_blocker_instructions"
    try:
        instructions_prompt = _register_if_changed(
            name=INSTRUCTIONS_PROMPT_NAME,
            template=INSTRUCTIONS,
            commit_message=f"Baseline instructions for GEPA ({RUN_LABEL})",
        )
        print(f"Instructions prompt URI: {instructions_prompt.uri if hasattr(instructions_prompt, 'uri') else 'N/A'}")
    except Exception as e:
        print(f"Cannot register instructions prompt: {e}")
        instructions_prompt = None

    if instructions_prompt is None:
        print("⚠ Skipping GEPA — Prompt Registry is unavailable.")
        RUN_GEPA = False
else:
    print("GEPA is OFF (set `run_gepa` widget to 'true' to enable).")

# COMMAND ----------

if RUN_GEPA:
    # Build the GEPA predict_fn: loads the current (GEPA-swapped) prompt version,
    # builds ai_classify SQL, and runs it for a single row.
    def gepa_predict_fn(opportunity_id, transcript_text):
        prompt = mlflow.genai.load_prompt(instructions_prompt.uri)
        current_instructions = prompt.template

        config = {"labels": LABELS, "instructions": current_instructions, "options": AI_OPTIONS}
        expr = build_ai_classify_expr("transcript_text", config)

        row_df = spark.createDataFrame([(transcript_text,)], ["transcript_text"])
        row_df.createOrReplaceTempView("_gepa_row")

        result = spark.sql(f"""
            SELECT transform(
                ({expr}):response::ARRAY<STRUCT<value:STRING,confidence_score:DOUBLE,rationale:STRING>>,
                x -> x.value
            ) AS pred_codes FROM _gepa_row
        """).collect()[0]

        codes = [c[:2] for c in (result.pred_codes or [])]
        return {"codes": codes}

    # Build train, validation, and test data in GEPA's required format.
    # - Train: GEPA evolves the prompt against this.
    # - Validation: GEPA selects the best candidate using this ("used up" by selection).
    # - Test: final honest check AFTER optimization finishes (GEPA never sees this).
    train_data_gepa = [
        {
            "inputs": {"opportunity_id": r.opportunity_id, "transcript_text": r.transcript_text},
            "expectations": {"expected_codes": list(r.expected_codes)},
        }
        for _, r in train_pd.iterrows()
    ]
    validation_data_gepa = [
        {
            "inputs": {"opportunity_id": r.opportunity_id, "transcript_text": r.transcript_text},
            "expectations": {"expected_codes": list(r.expected_codes)},
        }
        for _, r in validation_pd.iterrows()
    ]
    test_data_gepa = [
        {
            "inputs": {"opportunity_id": r.opportunity_id, "transcript_text": r.transcript_text},
            "expectations": {"expected_codes": list(r.expected_codes)},
        }
        for _, r in test_pd.iterrows()
    ]

    # Custom objective: micro-F1 over the scored rows.
    @scorer
    def gepa_micro_f1(outputs, expectations) -> Feedback:
        pred = _as_set(outputs)
        gold = _as_set(expectations.get("expected_codes"))
        tp = len(pred & gold)
        fp = len(pred - gold)
        fn = len(gold - pred)
        _, _, f1 = prf(tp, fp, fn)
        return Feedback(value=f1, rationale=f"row micro-F1={f1:.2f}")

    print(f"GEPA ready: {len(train_data_gepa)} train, {len(validation_data_gepa)} validation, {len(test_data_gepa)} test rows.")
    print("Starting optimization — this may take a while (one SQL call per row per iteration)...")

    try:
        gepa_result = mlflow.genai.optimize_prompts(
            predict_fn=gepa_predict_fn,
            train_data=train_data_gepa,
            prompt_uris=[instructions_prompt.uri],
            optimizer=GepaPromptOptimizer(
                max_metric_calls=50,
                display_progress_bar=True,
            ),
            scorers=[gepa_micro_f1],
        )

        optimized_template = gepa_result.optimized_prompts[0].template
        print(f"\nInitial score: {gepa_result.initial_eval_score}")
        print(f"Final score:   {gepa_result.final_eval_score}")
        print(f"\nOptimized instructions (first 500 chars):\n{optimized_template[:500]}...")

        # Register the optimized instructions
        optimized_prompt = mlflow.genai.register_prompt(
            name=INSTRUCTIONS_PROMPT_NAME,
            template=optimized_template,
            commit_message=f"GEPA-optimized ({gepa_result.initial_eval_score:.3f} → {gepa_result.final_eval_score:.3f})",
        )
        print(f"\n✓ Registered optimized instructions as v{optimized_prompt.version}")

        # --- Evaluate GEPA result on the UNTOUCHED TEST split for honest comparison ------
        # The validation split was "used up" by GEPA's selection process. Only the test
        # split gives a truly independent assessment.
        optimized_config = {"labels": LABELS, "instructions": optimized_template, "options": AI_OPTIONS}
        optimized_hash = hashlib.sha256(
            json.dumps(optimized_config, sort_keys=True).encode()
        ).hexdigest()[:16]

        # Cache the optimized config's predictions (full dataset for completeness)
        classify_and_cache(optimized_config, optimized_hash)

        # Run evaluate() on the TEST split only
        _gepa_cache = spark.sql(f"""
          SELECT opportunity_id, pred_codes, pred_confidences, pred_rationales
          FROM {CACHE_TABLE} WHERE config_hash = '{optimized_hash}'
        """).collect()
        _GEPA_PREDS = {
            r["opportunity_id"]: list(zip(r["pred_codes"] or [], r["pred_confidences"] or []))
            for r in _gepa_cache
        }
        _GEPA_RATS = {
            r["opportunity_id"]: (r["pred_rationales"] or [])
            for r in _gepa_cache
        }

        @mlflow.trace
        def gepa_test_predict_fn(opportunity_id, transcript_text):
            """Cache lookup for GEPA-optimized predictions."""
            pairs = _GEPA_PREDS.get(opportunity_id, [])
            codes = [c[:2] for (c, conf) in pairs if (conf is None or conf >= CONFIDENCE_THRESHOLD)]
            confidences = [conf for (c, conf) in pairs if (conf is None or conf >= CONFIDENCE_THRESHOLD)]
            rationales = _GEPA_RATS.get(opportunity_id, [])
            return {"codes": codes, "confidences": confidences, "rationales": rationales}

        with mlflow.start_run(run_name=f"{RUN_LABEL}_gepa_test_split") as gepa_test_run:
            mlflow.log_params({
                "config_hash": optimized_hash,
                "confidence_threshold": CONFIDENCE_THRESHOLD,
                "n_eval_rows": len(test_data_gepa),
                "split": "test (untouched by GEPA)",
                "source": "GEPA-optimized",
                "gepa_initial_score": gepa_result.initial_eval_score,
                "gepa_final_score": gepa_result.final_eval_score,
            })
            mlflow.log_dict(optimized_config, "prompt_config.json")

            gepa_test_result = mlflow.genai.evaluate(
                data=test_data_gepa,
                predict_fn=gepa_test_predict_fn,
                scorers=SCORERS,
            )

        print(f"\n{'='*60}")
        print(f"  GEPA HONEST TEST-SPLIT EVALUATION")
        print(f"  (this split was NEVER seen during optimization)")
        print(f"{'='*60}")
        print(f"  GEPA train score      : {gepa_result.initial_eval_score:.3f} → {gepa_result.final_eval_score:.3f}")
        print(f"  Test-split metrics    :")
        for k, v in sorted((gepa_test_result.metrics or {}).items()):
            print(f"    {k}: {v}")
        print(f"\n  ⚠ Compare the test-split numbers against the baseline's FULL-dataset")
        print(f"    numbers with caution — different denominators. The key question is:")
        print(f"    did GEPA find a GENERALIZABLE improvement, or did it overfit?")
        print(f"\n✓ GEPA-optimized config cached (hash={optimized_hash}).")
        print(f"  Compare runs in the Experiments UI or Section 11.")

    except Exception as e:
        print(f"⚠ GEPA failed: {type(e).__name__}: {e}")
        print("This may require mlflow>=3.5.0 and a supported workspace.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 13 — Promote the winning prompt
# MAGIC
# MAGIC Once a variant is a defensible improvement, **promote it** by setting the
# MAGIC `"production"` alias on its Prompt Registry version. The idea is that the production
# MAGIC pipeline will eventually read from this alias:
# MAGIC
# MAGIC ```python
# MAGIC # In the production pipeline (future state):
# MAGIC prompt = mlflow.genai.load_prompt(f"prompts:/{PROMPT_NAME}@production")
# MAGIC config = json.loads(prompt.template)
# MAGIC # ... build ai_classify SQL from config ...
# MAGIC ```
# MAGIC
# MAGIC **For now**, you copy the winning `LABELS` + `INSTRUCTIONS` back into
# MAGIC `gold_opportunity_enrichment.sql`. The registry alias is the path to automating
# MAGIC that handoff.

# COMMAND ----------

# Conditional promotion: only promote if we have a prompt version.
if PROMPT_VERSION:
    try:
        mlflow.genai.set_prompt_alias(
            name=PROMPT_NAME,
            alias="production",
            version=PROMPT_VERSION.version,
        )
        print(f"✓ Promoted '{PROMPT_NAME}' v{PROMPT_VERSION.version} to @production alias.")
        print(f"  Load it anywhere with: mlflow.genai.load_prompt('prompts:/{PROMPT_NAME}@production')")
    except Exception as e:
        print(f"(Could not set alias: {type(e).__name__}: {e})")
        print("The prompt version is still registered — promotion can be done manually in the UI.")
else:
    print("No Prompt Registry version to promote. The full config is logged as "
          "prompt_config.json on the MLflow run — copy LABELS + INSTRUCTIONS to the pipeline SQL.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 14 — Honest next steps
# MAGIC
# MAGIC ### 1. Grow and curate the labeled set
# MAGIC Your eval-set size sets the **ceiling** on how much you can trust *any* result.
# MAGIC The 3-way split (Section 3) means each label needs coverage in **all three**
# MAGIC partitions. Here are the targets:
# MAGIC
# MAGIC | | Total | Train (~70%) | Validation (~15%) | Test (~15%) |
# MAGIC |---|---|---|---|---|
# MAGIC | **Minimum pilot (GEPA)** | **200–400** | 140–280 | 30–60 | 30–60 |
# MAGIC | **Recommended** | **1,000–2,000** | 700–1,400 | 150–300 | 150–300 |
# MAGIC | **Per label (each split)** | | 30–50+ | 20–30+ | 20–30+ |
# MAGIC | empty / no-blocker | ~50% of total | Preserve natural prevalence | Same | Same |
# MAGIC
# MAGIC Because the eval table is a managed dataset, growth is cheap:
# MAGIC ```python
# MAGIC import mlflow.genai.datasets
# MAGIC ds = mlflow.genai.datasets.get_dataset("catalog.schema.your_eval_table")
# MAGIC ds.merge_records([
# MAGIC     {"inputs": {"opportunity_id": "...", "transcript_text": "..."},
# MAGIC      "expectations": {"expected_response": '["4B"]'}},
# MAGIC ])
# MAGIC ```
# MAGIC
# MAGIC **Audit label quality** — double-label a subset for inter-annotator agreement. At
# MAGIC small n, a mislabeled truth row is as damaging as a model error.
# MAGIC
# MAGIC ### 2. Integrate the Prompt Registry with the pipeline
# MAGIC Today, the pipeline hardcodes labels + instructions in SQL. The future state:
# MAGIC ```python
# MAGIC # In the pipeline's Python wrapper:
# MAGIC prompt = mlflow.genai.load_prompt(f"prompts:/{PROMPT_NAME}@production")
# MAGIC config = json.loads(prompt.template)
# MAGIC # Build the ai_classify SQL from `config` and inject it into the MV definition.
# MAGIC ```
# MAGIC This closes the loop: **tune here → promote → pipeline picks it up automatically**.
# MAGIC
# MAGIC ### 3. Measure model stochasticity
# MAGIC `ai_classify` is non-deterministic. To show the *second* noise floor, re-run one
# MAGIC config 3–5× with the cache cleared for that hash (delete from `ai_classify_eval_cache
# MAGIC WHERE config_hash = '...'`), and watch micro-F1 wobble with the prompt held fixed.
# MAGIC
# MAGIC ### 4. Production monitoring
# MAGIC Once the pipeline is reading from the registry, register an MLflow scorer against
# MAGIC the experiment and start production monitoring:
# MAGIC ```python
# MAGIC from mlflow.genai.scorers import ScorerSamplingConfig
# MAGIC quality_scorer = my_scorer.register(name="offer_blocker_quality")
# MAGIC quality_scorer.start(sampling_config=ScorerSamplingConfig(sample_rate=0.1))
# MAGIC ```
# MAGIC
# MAGIC ### 5. The qualifier layer
# MAGIC `gold_findings_raw` runs a finer-grained qualifier classification per code
# MAGIC (e.g. 4A → `current-supplier` / `competitor-rate` / …). The **same eval harness**
# MAGIC generalizes: swap the labels dict, build a parallel eval table, and re-use this
# MAGIC notebook's Sections 4–11 unchanged.
