# Talk-track validation + data scale-up report
**Workspace:** `adb-7405615135791589` · **Catalog:** `brlui.call_transcripts_poc` · **Date:** 2026-09-21

## Goal
1. Test the 7 `genie_one_demo_talktrack.md` prompts against the live Genie One agents.
2. Scale the data (transcripts + all downstream tables) so the demo feels like a real
   production environment with an abundance of data.

## What was done

### 1. Reusable validation harness — `genie_ext/genie_test_harness.py`
Starts a conversation on each target Genie space, polls to completion, and prints the
text answer, generated SQL, and row count. Runs all 7 talk-track prompts (or one via
`--only N`). Space IDs for all 5 extension agents are baked in.

### 2. Synthetic scale-up generator — `src/setup_ext/gen_scale_transcripts.py`
Additive notebook that generates an abundant, realistic transcript batch using the
shipped 19-record sample as the style/schema reference, then rebuilds
`dim_salesforce_opportunity` as a **superset** (original rows preserved).

- **Story-driven, skewed (not uniform)** per the synthetic-data-gen skill:
  - 7 dialogue archetypes → reliably classify to 4A–4F offer-blocker codes + clean/no-blocker calls.
  - Blocker mix **weighted toward 4A** (rate-strategy demo); ~25% clean calls.
  - A **wounded NY/NJ cohort** (~28%) carries degraded CX (long holds, abandons, low CSAT).
  - 4 teams / 8 skills / 14 agents so CX analytics group into meaningful cuts.
  - Stage mix ~ Closed Lost / Open / Closed Won for a rich reveal.
  - ~6% out-of-region phones to prove the silver region filter still drops them.
- Writes `batch_scale_001.json` into the landing Volume → the **existing** Auto Loader
  ingests it incrementally alongside the original batch. No pipeline transform changed.
- Deterministic (seeded) → re-running reproduces the same data.

Run as a one-off job (`n_opps=300, seed=42`).

### 3. Re-ran the real pipeline end-to-end (no shortcuts)
`gen_scale` → base `offer_blocker_pipeline` (bronze→gold AI enrichment; Auto Loader
self-restarted once to absorb the evolved schema, by design) → `genie_one_setup_ext_job`
(delivery seed) → `genie_one_ext_pipeline` (facts + base view) → `genie_one_metric_views_job`.

## Data volume: before → after

| Object | Before | After |
|---|---:|---:|
| dim_salesforce_opportunity | 16 | **316** |
| bronze/enriched calls (gold_call_enrichment_enh) | 19 | **508** |
| gold_opportunity_enrichment (opps) | 16 | **291** |
| gold_offer_blocker_summary (blocker rows) | ~7 | **404** |
| gold_followup_email_enh | 13 | **291** |
| ext_cx_contact | ~19 | **557** |
| ext_pricing_position | 16 | **291** |
| ext_delivery_order | ~40 | **858** |
| account_retention_base | 16 | **316** |
| **Churn-bomb accounts (High tier, 4A + verified failure)** | **2** | **76** |
| Blocker code 4A present? | **No (absent)** | **Yes — 89 opps, top blocker** |

## Talk-track validation results (all 7 COMPLETED, correct routing)

| # | Agent | Before (thin) | After (abundant) |
|---|---|---|---|
| 1 | Offer Blocker | 4 codes, 1 opp each, 4A absent | 6 codes; 4A = 29 Closed-Lost opps NY/NJ (2nd) |
| 2 | CX & Service Recovery | 1 team, hold 4.9/40.7s, 0 abandons | 4 teams; hold 23–102s; abandon 1.6–18.5% |
| 3 | Retention (reveal) | 2 accounts | **76 accounts**; top $23,795 / $18,093 |
| 4 | Retention | rate gap ok; **fee load = hold seconds (bug)** | rate gap ~0.16; **fee load ~$22 (fixed)** |
| 5 | Retention | 4 rows, all "Medium" | 66 Can-Raise vs 225 Protect, real tiers |
| 6 | Retention | 2 accounts | Top-5 Protect $20.8K→$11.0K each |
| 7 | Retention | $75K/$300K/$750K, BE 0.33pt | $225K/$450K/$900K, BE 0.33pt |

Baseline capture: `genie_ext/baseline_validation_before.log`
Post-scale capture: `genie_ext/validation_after_scaleup.log`

## One fix made during validation (additive)
**Q4 "fee load" resolved to `Avg Hold Seconds`** because `mv_retention` exposed no
fee-load measure (the base table already carried `fee_load`). Added an **`Avg Fee Load`**
measure (currency, synonyms: fee load / ancillary fees / monthly fees) to
`src/metric_views/mv_retention.metric_view.sql` and redeployed the metric-views job.
Re-tested: Q4 now returns rate gap **0.157** + fee load **$22.30** correctly.

## Rehearsal notes for the presenter (also in the talk track)
- **Q1** ranks by opportunity **count**, not dollars (`final_quoted_rate.amount` is sparse).
  Phrase as "which blockers affect the most Closed-Lost opportunities" for a clean ordering.
- **Q3 reveal**: the cohort is **76 accounts** (`Rate Objection And Failure` measure); the
  2-row result is the NY/NJ grouping. Say "76 accounts" not "2".
- Economics remain **illustrative, labeled** ($600/acct, $150k program, 100k base) — not booked EBITDA.

## Additive & non-destructive
- New files only: the generator, the harness, this report, two validation logs, and one
  new measure in the (extension-owned) `mv_retention` file.
- No existing pipeline transform, table, or object was modified. The scale generator only
  lands a new file and rebuilds the extension-adjacent `dim_salesforce_opportunity` as a
  superset (the same object the original `setup.py` owns/overwrites).
