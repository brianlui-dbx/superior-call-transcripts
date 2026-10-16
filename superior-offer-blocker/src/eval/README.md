# Evaluating & Tuning the `ai_classify` Offer-Blocker Classifier

A single, idempotent Databricks notebook that teaches you how to **measure** and
**tune** the prompt behind the `ai_classify` call in `gold_opportunity_enrichment`,
using **MLflow** as the scaffolding — and, just as importantly, **when not to
over-engineer it**.

> **New to Databricks + MLflow?** This is written for you. Read this page, then run
> `ai_classify_eval_and_tuning.py` top-to-bottom.

---

## The one idea to internalize

**We are not evaluating a *model*. We are evaluating a *prompt*.**

The foundation model behind `ai_classify` is fixed. What we tune is a prompt that
lives in **two surfaces**:

1. the six **label descriptions** (the routing rules for codes **4A–4F**), and
2. the global **instructions** string (when to assign *anything* at all).

So a "model version" here **is** a `(descriptions + instructions + options)` bundle,
and evaluation is just a function: `prompt_config → accuracy metrics`.

Everything in the notebook follows from that:
- One **Prompt Registry version = one prompt config**, versioned in Unity Catalog.
- One **MLflow run = one evaluation** of a prompt version, so you compare side-by-side.
- The expensive step (one LLM call per transcript) is cached by `config_hash` — re-runs
  are free and deterministic.

---

## The system under test

`gold_opportunity_enrichment` runs **one** `ai_classify(...)` per sales-call
transcript. It is **multilabel** (0..N codes per call) with confidence scores and
per-label rationales enabled.

| Code | Meaning (abbreviated) |
|------|-----------------------|
| 4A | Rate/price uncompetitive — the quoted per-unit rate itself is too high |
| 4B | Ancillary fees — delivery / tank-rental / install / MUC / admin fees paid *while* a customer |
| 4C | Commercial model mismatch — wants a different deal *shape* (pre-buy, tank ownership, fixed-vs-variable, term) |
| 4D | Contract/transaction mechanics — auto-renewal, exit/cancellation, payment terms, e-sign gating |
| 4E | Availability/serviceability gap — a *physical* limit (coverage, product, equipment, timeline) |
| 4F | Promotion ineligibility — wanted a promo/credit/referral and was **denied** |

The codes that get **confused** (and therefore where tuning effort goes) are the
adjacent boundaries **4A ↔ 4B ↔ 4C** and **4C ↔ 4D**.

---

## The ground truth

`dbw_brlui_stable.call_transcripts_poc.code_classification_eval_dataset` is an
**MLflow managed evaluation dataset** (Unity-Catalog-backed). Each row has:

- `inputs` → `{"opportunity_id": "...", "transcript_text": "..."}`
- `expectations` → `{"expected_response": "[\"4B\",\"4C\"]"}` (a multilabel array;
  `[]` means **no blocker**)

---

## How the notebook is structured

| Phase | §§ | What happens |
|-------|----|--------------|
| **Setup** | 0–1 | Parameters, prompt config, **register in Prompt Registry** |
| **Data** | 2–3 | Load managed eval dataset, inspect class balance, **3-way train/validation/test split** |
| **Score** | 4–7 | Build SQL, cache predictions, `mlflow.genai.evaluate()`, corpus metrics |
| **Diagnose** | 8–10 | Error analysis + substitution matrix, iteration guide + threshold sweep |
| **Compare** | 11 | Programmatic side-by-side of all runs |
| **Optimize** | 12 | (Optional, gated) GEPA automated prompt optimization |
| **Ship** | 13–14 | Promote winning prompt, next steps |

---

## Key MLflow features used

### Prompt Registry (Section 1 & 13)
Each prompt variant is a **versioned artifact** in Unity Catalog, not a string in a
code cell. The iteration loop is: edit → register new version → evaluate → compare →
promote the winner with a `"production"` alias. Eventually, the production pipeline
reads from this alias rather than hardcoded SQL.

### `mlflow.genai.evaluate()` (Section 6)
The standard GenAI evaluation API, with:
- **`predict_fn`** that receives `**kwargs` (not a dict) — unpacked from `inputs`
- **Custom `@scorer` functions** returning `Feedback` objects (per-label hits visible
  in the Trace UI per-row)
- **Corpus-wide metrics** (`micro_f1`, `macro_f1`, `mean_jaccard`, `abstain_accuracy`)
  logged to the same run via `log_metrics`

### Managed Datasets (Section 2)
Loaded via `mlflow.genai.datasets.get_dataset()` (with a Spark fallback), the native
MLflow way to work with UC-backed eval data.

### GEPA / `optimize_prompts()` (Section 12)
Automated prompt evolution — optimizes the **instructions** string (the semantic
surface) while holding descriptions fixed (the structured routing rules). Gated behind
a widget because it's slow and costly (one SQL call per row per GEPA iteration). Uses
a **3-way split** (Section 3) — train for optimization, validation for selecting the
best candidate, and a held-out **test split** for the final honest check — to prevent
overfitting.

---

## Metrics: what we report and why

| Metric | Role | Watch out |
|--------|------|-----------|
| **Micro-F1** | **Headline.** Pools all n×6 label decisions — the real sample size. | Moves ~`6/(n*6)`% per flipped row. |
| **Mean Jaccard** | Human-intuitive partial credit per row (`∅,∅ → 1.0`). | — |
| **Abstain accuracy** | On empty-ground-truth rows, did we assign nothing? **Biggest lever.** | — |
| **Macro-F1** | Reported with a warning; excludes codes with ≤2 positives. | Whiplashes on small classes. |
| **Per-label TP/FP/FN** | Integer counts ("3 of 4"), not bare rates. | "0.75" hides a denominator of 4. |
| **Per-label Feedback** | Visible per-row in the MLflow Trace UI. | — |
| **Exact-match** | Sanity stat only — brutal for multilabel. | Never the optimization target. |

**Row-wise vs corpus-wide** is a core lesson: Jaccard/exact-match/abstain/per-label
are `@scorer` functions (per-row in the UI); precision/recall/F1 need the whole set
and are computed + `log_metrics`'d separately.

---

## The tuning loop — which surface do I edit?

Match the **error signature** (from Section 8) to the **lever**, and change **one
surface per iteration**:

| Error signature | Lever |
|-----------------|-------|
| **Substitution** — right evidence, wrong code (4A/4B/4C, 4C/4D) | Edit the **DESCRIPTIONS** of *both* codes contrastively — add a discriminator + a "NOT this if…" clause to each side. Edit boundaries **in pairs**. |
| **Empty-class false positive** — assigned on a no-blocker call | Edit the **INSTRUCTIONS** (raise the evidence bar; reinforce "benchmarking-only ⇒ no code"). |
| **Misses** — true codes, predicted none / too timid | Edit the **INSTRUCTIONS** or **lower the threshold**. |
| **Systematic over/under across all codes** | Sweep the **CONFIDENCE THRESHOLD** first — it's free and touches no prompt. |

Use confidence to pick the lever: **low-confidence** false positives → threshold;
**high-confidence** false positives → it's semantic (description/instructions) and no
threshold will save you.

> **Golden rule:** keep an edit only if it fixes a **class** of error for an
> articulable, generalizable reason — never because one row's number went up.

### To run an iteration
1. Edit **one** surface in Section 1 (descriptions *or* instructions, not both).
2. Set a new `run_label` (e.g. `v2_tighten_4B_vs_4A`).
3. Re-run from Section 0. A new Prompt Registry version is created automatically;
   the cache re-scores **only** the new config; everything else is instant.
4. Compare runs in the **Experiments UI** or **Section 11** (programmatic table).

---

## When to use GEPA vs manual tuning

| | Manual tuning (Sections 8–10) | GEPA (Section 12) |
|---|---|---|
| **Best for** | Boundary errors (descriptions), under/over-assignment (instructions) | Plateau-breaking on instructions after manual gains stall |
| **Dataset size** | Any (even small) | 200–400+ total rows; ≥30 per label per split |
| **Splits** | Evaluates on **full** dataset (generalizable edits) | **3-way**: train (70%) / validation (15%) / test (15%) |
| **Surface** | Either (descriptions or instructions) | Instructions only (GEPA would break contrastive descriptions) |
| **Cost** | Free (edits cached predictions) | Expensive (1 SQL call × n_train × GEPA iterations) |
| **Transparency** | You read rationales and understand every edit | GEPA outputs opaque evolved text |

### Why 3 splits, not 2?

| Split | Purpose | Who sees it |
|-------|---------|-------------|
| **Train** (~70%) | What GEPA optimizes against | GEPA |
| **Validation** (~15%) | Picks the winning prompt candidate | GEPA (for selection — "used up") |
| **Test** (~15%) | Final honest check | **Nobody until final eval** |

The validation set is compromised by *selection*: repeatedly choosing the prompt that
scores best on it can overfit to that set, even though GEPA didn't directly train on
it. The test set is the only truly independent assessment. Think of it as "train is
for learning, validation is for choosing, test is for believing."

---

## Prerequisites

- **Compute:** serverless, or a Pro/Serverless-capable runtime (`ai_classify` requires
  it).
- **Access:** read on the eval table; create/write on
  `dbw_brlui_stable.call_transcripts_poc` for the cache + prompt-registry objects.
- **Library:** `mlflow[databricks] >= 3.5` (installed by the notebook's first cell).
  GEPA specifically requires `>= 3.5.0`.

## Parameters (widgets)

| Widget | Default | Purpose |
|--------|---------|---------|
| `catalog` | `dbw_brlui_stable` | Unity Catalog |
| `schema` | `call_transcripts_poc` | Schema |
| `eval_table` | `code_classification_eval_dataset` | Ground-truth managed dataset |
| `experiment_path` | *(blank)* | MLflow experiment (blank = notebook default) |
| `run_label` | `baseline_v1` | Human name for this prompt variant |
| `confidence_threshold` | `0.0` | Keep labels with confidence ≥ this |
| `run_gepa` | `false` | Run GEPA automated optimization? |

## Objects the notebook creates

- **`ai_classify_eval_cache`** — Delta cache of predictions, keyed by `config_hash`.
- **`offer_blocker_ai_classify_prompt`** — Prompt Registry entry; one version per
  prompt variant, with `"production"` alias on the promoted winner.
- **`offer_blocker_instructions`** — (GEPA only) Prompt Registry entry for the
  instructions string, optimized by GEPA.
- **One MLflow run per `run_label`**, with params, metrics, `prompt_config.json`,
  `per_label_metrics.json`, and the substitution-matrix figure.

## Promoting a tuned prompt back to the pipeline

**Today:** copy the winning `LABELS` + `INSTRUCTIONS` from Section 1 back into
[`pipeline/transformations/gold/gold_opportunity_enrichment.sql`](../../pipeline/transformations/gold/gold_opportunity_enrichment.sql).

**Future:** the pipeline reads from the Prompt Registry's `@production` alias:
```python
prompt = mlflow.genai.load_prompt(f"prompts:/{PROMPT_NAME}@production")
config = json.loads(prompt.template)
# Build ai_classify SQL from config
```
