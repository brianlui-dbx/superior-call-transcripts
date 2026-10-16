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

All prompt content is sourced from the **master evaluation prompt**
(`examples/Module 2 - Offer Blocker AI Prompt v6.docx`), which is the authoritative
source of truth for code definitions, qualifiers, boundary rules, and calibration
examples. The descriptions distill Section 6 per-code text to ≤1,000 chars each; the
instructions include verbatim Sections 1, 3, 6 **preamble** (shared assignment engine,
dispositions, boundary litmus — NOT the per-code definitions, which live in descriptions),
and 7 (~10K chars, within `ai_classify`'s 20K-char instruction limit).

Everything in the notebook follows from that:
- **Two registered prompts** in the Prompt Registry: `offer_blocker_descriptions`
  (JSON dict) and `offer_blocker_instructions` (free text) — plus a
  `offer_blocker_ai_classify_prompt` bundle for the full config.
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
adjacent boundaries **4A ↔ 4C**, **4B ↔ 4C**, **4B ↔ 4D**, and **4C ↔ 4D**.

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
|-------|----|--------------:|
| **Setup** | 0–1 | Parameters, prompt config, **register in Prompt Registry** (2 surface prompts + 1 bundle) |
| **Data** | 2–3 | Load managed eval dataset, inspect class balance, **3-way train/validation/test split** |
| **Score** | 4–7 | Build SQL, cache predictions, `mlflow.genai.evaluate()`, corpus metrics + boundary confusion |
| **Diagnose** | 8–10 | Error analysis + substitution matrix, iteration guide + threshold sweep |
| **Compare** | 11 | Programmatic side-by-side of all runs (filterable by GEPA phase) |
| **Optimize** | 12a–12d | (Optional, gated) GEPA automated prompt optimization — **phase-gated**: descriptions / instructions / joint |
| **Ship** | 13–14 | Promote winning prompt, next steps + GEPA phase sequencing guide |

---

## Key MLflow features used

### Prompt Registry (Section 1 & 13)
Each prompt variant is a **versioned artifact** in Unity Catalog. We maintain **three**
registered prompts:

| Prompt | Content | GEPA optimizes? |
|--------|---------|-----------------|
| `offer_blocker_descriptions` | JSON dict of 6 label descriptions | Yes (phase `descriptions` or `joint`) |
| `offer_blocker_instructions` | Free-text instructions string | Yes (phase `instructions` or `joint`) |
| `offer_blocker_ai_classify_prompt` | Full `{labels, instructions, options}` bundle | No (snapshot for reproducibility) |

The iteration loop: edit → register new version → evaluate → compare → promote with
a `"production"` alias.

### `mlflow.genai.evaluate()` (Section 6)
The standard GenAI evaluation API, with:
- **`predict_fn`** that receives `**kwargs` — unpacked from `inputs`
- **Custom `@scorer` functions** returning `Feedback` objects (per-label hits +
  **boundary confusion** visible in the Trace UI per-row)
- **Corpus-wide metrics** (`micro_f1`, `macro_f1`, `mean_jaccard`, `abstain_accuracy`,
  `boundary_confusion_rate`) logged to the same run via `log_metrics`

### Managed Datasets (Section 2)
Loaded via `mlflow.genai.datasets.get_dataset()` (with a Spark fallback), the native
MLflow way to work with UC-backed eval data.

### GEPA / `optimize_prompts()` (Section 12)
Automated prompt evolution with **phase-gated** optimization:

| Phase | Widget value | What moves | Best for |
|-------|-------------|-----------|----------|
| **descriptions** | `descriptions` | Label descriptions only | Substitution/boundary errors (bucket C) |
| **instructions** | `instructions` | Instructions string only | Over/under-assignment (buckets A/B/E) |
| **joint** | `joint` | Both surfaces | After single-surface phases plateau |

Uses a **3-way split** (Section 3) — train for optimization, validation for selection,
test for honest final check. Description candidates are validated by a **structural
validator** (6 keys, valid JSON, ≤1,000 chars/value).

---

## Metrics: what we report and why

| Metric | Role | Watch out |
|--------|------|-----------|
| **Micro-F1** | **Headline.** Pools all n×6 label decisions — the real sample size. | Moves ~`6/(n*6)`% per flipped row. |
| **Mean Jaccard** | Human-intuitive partial credit per row (`∅,∅ → 1.0`). | — |
| **Abstain accuracy** | On empty-ground-truth rows, did we assign nothing? **Biggest lever.** | — |
| **Boundary confusion rate** | % of rows with a boundary swap between adjacent codes. | New — signals description editing priority. |
| **Macro-F1** | Reported with a warning; excludes codes with ≤2 positives. | Whiplashes on small classes. |
| **Per-label TP/FP/FN** | Integer counts ("3 of 4"), not bare rates. | "0.75" hides a denominator of 4. |
| **Exact-match** | Sanity stat only — brutal for multilabel. | Never the optimization target. |

---

## The tuning loop — which surface do I edit?

Match the **error signature** (from Section 8) to the **lever**, and change **one
surface per iteration**:

| Error signature | Lever |
|-----------------|-------|
| **Substitution** — right evidence, wrong code (4A/4C, 4C/4D) | Edit the **DESCRIPTIONS** of *both* codes contrastively — add a discriminator + a "NOT this if…" clause to each side. Edit boundaries **in pairs**. |
| **Empty-class false positive** — assigned on a no-blocker call | Edit the **INSTRUCTIONS** (raise the evidence bar; reinforce "benchmarking-only ⇒ no code"). |
| **Misses** — true codes, predicted none / too timid | Edit the **INSTRUCTIONS** or **lower the threshold**. |
| **Systematic over/under across all codes** | Sweep the **CONFIDENCE THRESHOLD** first — it's free and touches no prompt. |

> **Golden rule:** keep an edit only if it fixes a **class** of error for an
> articulable, generalizable reason — never because one row's number went up.

---

## GEPA phase sequencing (recommended order)

1. **`instructions` first** — fixes over/under-assignment (the biggest lever). After
   convergence, promote the winning instructions and set them as the new baseline.
2. **`descriptions` second** — fixes boundary/substitution errors. With better
   instructions as baseline, description optimization is more focused.
3. **`joint` last** — only if single-surface phases have plateaued. The joint search
   space is much larger, so it needs more iterations and more data.

Between phases, **update the baseline**: copy GEPA-optimized text back into Section 1,
set a new `run_label`, and re-evaluate on the full dataset to confirm before proceeding.

---

## When to use GEPA vs manual tuning

| | Manual tuning (Sections 8–10) | GEPA (Section 12) |
|---|---|---|
| **Best for** | Boundary errors (descriptions), under/over-assignment (instructions) | Plateau-breaking after manual gains stall |
| **Dataset size** | Any (even small) | 200–400+ total rows; ≥30 per label per split |
| **Splits** | Evaluates on **full** dataset (generalizable edits) | **3-way**: train (70%) / validation (15%) / test (15%) |
| **Surface** | Either (descriptions or instructions) | Either or both (phase-gated) |
| **Cost** | Free (edits cached predictions) | Expensive (1 SQL call × n_train × GEPA iterations) |
| **Transparency** | You read rationales and understand every edit | GEPA outputs opaque evolved text |

### Why 3 splits, not 2?

| Split | Purpose | Who sees it |
|-------|---------|-------------|
| **Train** (~70%) | What GEPA optimizes against | GEPA |
| **Validation** (~15%) | Picks the winning prompt candidate | GEPA (for selection — "used up") |
| **Test** (~15%) | Final honest check | **Nobody until final eval** |

---

## Prerequisites

- **Compute:** serverless, or a Pro/Serverless-capable runtime (`ai_classify` requires it).
- **Access:** read on the eval table; create/write on
  `dbw_brlui_stable.call_transcripts_poc` for the cache + prompt-registry objects.
- **Libraries:** `mlflow[databricks] >= 3.5` and `gepa >= 0.0.26` (installed by the
  notebook's first cell).

## Parameters (widgets)

| Widget | Default | Purpose |
|--------|---------|---------|
| `catalog` | `dbw_brlui_stable` | Unity Catalog |
| `schema` | `call_transcripts_poc` | Schema |
| `eval_table` | `code_classification_eval_dataset` | Ground-truth managed dataset |
| `experiment_path` | *(blank)* | MLflow experiment (blank = notebook default) |
| `run_label` | `baseline_v1` | Human name for this prompt variant |
| `confidence_threshold` | `0.0` | Keep labels with confidence ≥ this |
| `run_gepa` | `true` | Run GEPA automated optimization? |
| `gepa_phase` | `instructions` | Which surface(s) GEPA optimizes: `descriptions` / `instructions` / `joint` |

## Objects the notebook creates

- **`ai_classify_eval_cache_v3`** — Delta cache of predictions, keyed by `config_hash`.
- **`offer_blocker_descriptions`** — Prompt Registry entry for the descriptions JSON.
- **`offer_blocker_instructions`** — Prompt Registry entry for the instructions string.
- **`offer_blocker_ai_classify_prompt`** — Prompt Registry entry for the full config
  bundle; one version per prompt variant, with `"production"` alias on the promoted
  winner.
- **One MLflow run per `run_label`**, with params, metrics, `prompt_config.json`,
  `per_label_metrics.json`, and the substitution-matrix figure.

## Promoting a tuned prompt back to the pipeline

**Today:** copy the winning `LABELS` + `INSTRUCTIONS` from Section 1 back into
[`pipeline/transformations/gold/gold_opportunity_enrichment.sql`](../../pipeline/transformations/gold/gold_opportunity_enrichment.sql).

**Future:** the pipeline reads from the Prompt Registry's `@production` alias:
```python
prompt = mlflow.genai.load_prompt(f"prompts:/{BUNDLE_PROMPT_NAME}@production")
config = json.loads(prompt.template)
# Build ai_classify SQL from config
```
