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
- One **MLflow run = one prompt config**, so you can compare variants side-by-side.
- The expensive step (one LLM call per transcript) is a pure function of
  `(transcript, config, model)` → it is **cached and deterministic**, which is how a
  single notebook stays idempotent.

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

### ⚠️ Read this before you trust any number

This eval set is **tiny and imbalanced**:

| | value |
|---|---|
| total rows | **24** |
| empty / no-blocker | **12 (50%)** |
| 4A positives | **1** |
| 4B / 4C / 4D positives | 4 each |
| 4E / 4F positives | 3 each |

That single fact reshapes the whole exercise:

- This is **not** an optimization problem. It is a **structured, rationale-driven
  error analysis** with a *thin quantitative guardrail*.
- Metrics are a **regression smoke-test**, not a leaderboard. **One row flipping moves
  micro-F1 by ~4 points** — that is noise, not progress.
- **Code 4A (n=1) is a unit test, not a metric.** Its per-label F1 can only be 0.0 or
  1.0; it measures nothing generalizable.
- The honest **#1 priority is not a tuned prompt** — it is growing and curating the
  labeled set (see below).

---

## How the notebook is structured

| § | Section | Teaching point |
|---|---------|----------------|
| 0 | Setup, parameters & prompt config | Nothing hardcoded; the config is one hashed object |
| 1 | Load ground truth & **look at it first** | Inspect class balance before measuring |
| 2 | Build the `ai_classify` SQL from the config | Pipeline & eval can never drift apart |
| 3 | Reproducibility cache | `config_hash`-keyed Delta table → real idempotency |
| 4 | Deterministic scorers | Compare sets in Python; no LLM judge needed |
| 5 | `mlflow.genai.evaluate()` run | `predict_fn` is a pure cache lookup (no LLM call) |
| 6 | Corpus metrics + noise panel | Micro-F1 headline; macro-F1 flagged; integer TP/FP/FN |
| 7 | **Error analysis** | Read rationales row-by-row; bucket mistakes — *the main event* |
| 8 | Iteration decision guide | Which surface to edit for which error |
| 9 | Confidence-threshold sweep | A free precision/recall knob |
| 10 | Register the tuned prompt | Durable handoff artifact in the Prompt Registry |
| 11 | Honest next steps | Why not GEPA; grow/curate the set; promotion path |

---

## Metrics: what we report and why

| Metric | Role | Watch out |
|--------|------|-----------|
| **Micro-F1** | **Headline.** Pools all 24×6 = **144 label decisions** — the real sample size, and the steadiest number. | Still moves ~4 pts per row. |
| **Mean Jaccard** | Human-intuitive partial credit per row (`∅,∅ → 1.0`). | — |
| **Abstain accuracy** | On rows that should be empty, did we assign nothing? **Biggest lever (50% of data).** | — |
| **Macro-F1** | Reported, but **excludes 4A** and averages tiny classes. | Whiplashes — treat as noisy. |
| **Per-label TP/FP/FN** | Integer counts ("3 of 4"), not bare rates. | "0.75" hides a denominator of 4. |
| **Exact-match** | Sanity stat only — brutal for multilabel. | Never the optimization target. |

**Row-wise vs corpus-wide** is a core lesson: Jaccard/exact-match/abstain are per-row
MLflow `@scorer`s; precision/recall/F1 need the whole set at once and are computed in a
plain cell, then `log_metrics`'d into the same run.

---

## The tuning loop — which surface do I edit?

Match the **error signature** (from Section 7) to the **lever**, and change **one
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
> articulable, generalizable reason — never because one row's number went up. At n=24,
> one row moving is almost always noise.

### To run an iteration
1. Duplicate the config cell in **Section 0**.
2. Edit **one** surface (one or two descriptions, *or* the instructions, *or* the
   threshold widget).
3. Set a new `run_label` (e.g. `v2_tighten_4B_vs_4A`).
4. Re-run from Section 0. The cache re-scores **only** the new config; everything else
   is instant.
5. Compare runs in the **Experiments UI** — it reads like a changelog.

---

## Why we do NOT run GEPA / `optimize_prompts` here

Automated prompt optimization is the right tool *later* and the wrong tool *now*:

- **No honest validation split.** A held-out from 24 rows is ~5 rows, and **4A's one
  example cannot be in both train and validation** — class-level signal is impossible.
- **Its signal is the metric, and the metric is noise here.** It would memorize these
  24 transcripts (learning the labels, not the task) with no instrument able to detect
  the lost generalization.
- **It removes the rationale-reading that is the actual value at this scale** and emits
  opaque evolved text a newcomer can't reason about.

The notebook **shows the hook, commented out**, with guidance on when to pull it
(hundreds of rows + a real held-out split).

---

## Your real #1 priority: grow & curate the labeled set

Your eval-set size sets the **ceiling** on how much you can trust *any* result —
manual or automated.

| Code | Now | Target (min usable) |
|------|-----|---------------------|
| empty / no-blocker | 12 | keep ~40–50% of total |
| 4A | **1** | ~10 |
| 4B–4D | 4 each | ~10–15 each |
| 4E–4F | 3 each | ~10–15 each |
| **total** | **24** | **~150–300** |

Because it is a managed dataset, growth is cheap: **append rows, re-run this same
notebook, same scorers.** Also **audit label quality** — at n=24 a mislabeled truth row
is about as damaging as a model error, so double-label a subset and re-adjudicate every
disagreement your rationales surface.

---

## Prerequisites

- **Compute:** serverless, or a Pro/Serverless-capable runtime (`ai_classify` is not
  available on SQL Warehouse Classic).
- **Access:** read on the eval table; create/write on
  `dbw_brlui_stable.call_transcripts_poc` for the cache + prompt-registry objects.
- **Library:** `mlflow[databricks] >= 3.1` (installed by the notebook's first cell).

## Parameters (widgets)

| Widget | Default | Purpose |
|--------|---------|---------|
| `catalog` | `dbw_brlui_stable` | Unity Catalog |
| `schema` | `call_transcripts_poc` | Schema |
| `eval_table` | `code_classification_eval_dataset` | Ground-truth managed dataset |
| `experiment_path` | *(blank)* | MLflow experiment (blank = notebook default) |
| `run_label` | `baseline_v1` | Human name for this prompt variant |
| `confidence_threshold` | `0.0` | Keep labels with confidence ≥ this |

## Objects the notebook creates

- `dbw_brlui_stable.call_transcripts_poc.ai_classify_eval_cache` — Delta cache of
  predictions, keyed by `config_hash` (safe to re-run; never dropped).
- `dbw_brlui_stable.call_transcripts_poc.offer_blocker_ai_classify_prompt` — registered
  prompt (best-effort; skipped gracefully on older MLflow).
- One MLflow run per `run_label`, with params, metrics, `prompt_config.json`,
  `per_label_metrics.json`, and the substitution-matrix figure.

## Promoting a tuned prompt back to the pipeline

Copy the winning `LABELS` + `INSTRUCTIONS` from the Section-0 config back into
[`pipeline/transformations/gold/gold_opportunity_enrichment.sql`](../../pipeline/transformations/gold/gold_opportunity_enrichment.sql).
Because the notebook builds its `ai_classify` SQL from the same two surfaces, what you
evaluated is exactly what the pipeline will run.
