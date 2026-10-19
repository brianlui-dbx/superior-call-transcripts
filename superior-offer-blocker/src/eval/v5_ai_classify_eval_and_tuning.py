# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# MAGIC %md
# MAGIC # Evaluating & Tuning the `ai_classify` Offer-Blocker Classifier (v5)
# MAGIC
# MAGIC This notebook teaches you how to *think through*, *measure*, and *tune* the
# MAGIC prompt behind an `ai_classify` call — using MLflow as the scaffolding.
# MAGIC
# MAGIC ## What are we evaluating?
# MAGIC `gold_opportunity_enrichment` runs **one** `ai_classify(...)` per sales-call
# MAGIC transcript. It is **multilabel**: a transcript can receive 0..N "offer-blocker"
# MAGIC codes (**4A–4F**). The foundation model is fixed — the thing we actually tune is a
# MAGIC **prompt**, split across **two surfaces**:
# MAGIC
# MAGIC 1. **Label descriptions** — per-code routing rules (≤1,000 chars each)
# MAGIC 2. **Instructions** — shared decision framework (≤20,000 chars)
# MAGIC
# MAGIC > *We are not evaluating a model; we are evaluating a prompt.*
# MAGIC
# MAGIC ## How this notebook is organized
# MAGIC
# MAGIC | Phase | Sections | What happens |
# MAGIC |-------|----------|--------------|
# MAGIC | **Setup** | 0–1 | Parameters, prompt config, Prompt Registry |
# MAGIC | **Data** | 2–3 | Load managed eval dataset, class balance, train/validation/test split |
# MAGIC | **Score** | 4–7 | Build SQL, cache predictions, `mlflow.genai.evaluate()`, corpus metrics |
# MAGIC | **Diagnose** | 8–10 | Error analysis, substitution matrix, decision guide + threshold sweep |
# MAGIC | **Compare** | 11 | Programmatic side-by-side of all runs |
# MAGIC | **Optimize** | 12 | GEPA automated prompt optimization (phase-gated) |
# MAGIC | **Ship** | 13–14 | Promote winner + next steps |
# MAGIC
# MAGIC The notebook is **idempotent**: re-runs reuse cached predictions and produce the
# MAGIC same experiment state.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 0 — Setup & parameters

# COMMAND ----------

# MAGIC %pip install -q -U "mlflow[databricks]>=3.5" "gepa>=0.0.26"
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "dbw_brlui_stable", "Catalog")
dbutils.widgets.text("schema", "call_transcripts_poc", "Schema")
dbutils.widgets.text("eval_table", "code_classification_eval_dataset", "Ground-truth eval dataset")
dbutils.widgets.text("experiment_path", "", "MLflow experiment path (blank = notebook default)")
dbutils.widgets.text("run_label", "baseline_v5", "Human name for THIS prompt variant")
dbutils.widgets.text("confidence_threshold", "0.0", "Keep labels with confidence >= this")
dbutils.widgets.dropdown("run_gepa", "true", ["false", "true"], "Run GEPA automated optimization?")
dbutils.widgets.dropdown(
    "gepa_phase", "joint",
    ["descriptions", "instructions", "joint"],
    "GEPA phase: which surface(s) to optimize",
)

# COMMAND ----------

import json, hashlib, uuid
import numpy as np
import uuid
import pandas as pd
import matplotlib.pyplot as plt
import mlflow
from mlflow.genai.scorers import scorer
from mlflow.entities import Feedback
from pyspark.sql import functions as F

# COMMAND ----------

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
EVAL_TABLE = f"{CATALOG}.{SCHEMA}.{dbutils.widgets.get('eval_table')}"
CACHE_TABLE = f"{CATALOG}.{SCHEMA}.ai_classify_eval_cache_v5"
DESCRIPTIONS_PROMPT_NAME = f"{CATALOG}.{SCHEMA}.offer_blocker_descriptions_v5"
INSTRUCTIONS_PROMPT_NAME = f"{CATALOG}.{SCHEMA}.offer_blocker_instructions_v5"
BUNDLE_PROMPT_NAME = f"{CATALOG}.{SCHEMA}.offer_blocker_ai_classify_prompt_v5"
RUN_LABEL = dbutils.widgets.get("run_label")
CONFIDENCE_THRESHOLD = float(dbutils.widgets.get("confidence_threshold"))
RUN_GEPA = dbutils.widgets.get("run_gepa") == "true"
GEPA_PHASE = dbutils.widgets.get("gepa_phase")
CODE_PREFIXES = ["4A", "4B", "4C", "4D", "4E", "4F"]

_exp = dbutils.widgets.get("experiment_path").strip()
if _exp:
    mlflow.set_experiment(_exp)
    print(f"Using experiment: {_exp}")
else:
    print("Using the notebook's default experiment.")

print(f"Ground truth : {EVAL_TABLE}")
print(f"Cache table  : {CACHE_TABLE}")
print(f"Run label    : {RUN_LABEL}  |  τ={CONFIDENCE_THRESHOLD}  |  GEPA={RUN_GEPA} ({GEPA_PHASE})")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 1 — Prompt config & Prompt Registry
# MAGIC
# MAGIC **Two tunable surfaces, two registered prompts.** GEPA can optimize each
# MAGIC independently.
# MAGIC
# MAGIC | Prompt | Content | GEPA? |
# MAGIC |--------|---------|-------|
# MAGIC | `offer_blocker_descriptions_v5` | JSON dict of 6 label descriptions (≤1,000 chars each) | descriptions / joint |
# MAGIC | `offer_blocker_instructions_v5` | Shared decision framework from master eval prompt | instructions / joint |

# COMMAND ----------

# MAGIC %md
# MAGIC ### Surface 1 — Label descriptions
# MAGIC
# MAGIC Each description maxed at ~1,000 characters — distilled from the master eval
# MAGIC prompt rubric (Section 6). Structure: definition → assign-when → qualifiers →
# MAGIC do-not-assign → reasoning anchor.

# COMMAND ----------

LABELS = {
    '4A. Rate/price uncompetitive': (
        "Superior's quoted unit rate – propane or oil – or the customer's comparison of the "
        "rate, materially affected willingness to proceed: negotiation, escalation, "
        "concession, delay, continued shopping, or rejection. Assign when: customer states "
        "rate is too high; compares rate unfavourably with current supplier, competitor, or "
        "advertised rate; provides credible comparison causing price-match request or revised "
        "quote; delays or declines because of rate. Qualifiers: current-supplier, "
        "competitor-rate, advertised-rate, high-rate, rate-increase, price-match, other. Do "
        "not assign: generic price concern before specific rate quoted; non-rate fees (→ 4B); "
        "rate DESIGN/variability/Year-2 uncertainty (→ 4C); rep-volunteered discount without "
        "customer pressure; concern resolved by accurate explanation; promotion customer could "
        "not get (→ 4F). Reasoning anchor: would the deal have changed if SUPERIOR lowered the "
        "per-unit rate? Yes → 4A. Lowering fees or restructuring deal shape → 4B or 4C."
    ),
    '4B. Ancillary fees barrier': (
        "The fee stack – delivery, tank rental, installation, MUC, inspection, monitoring, or "
        "admin fees – charges paid WHILE a customer – materially blocked or degraded the deal. "
        "Two grounds: objection (customer pushed back, affecting progression) or economics "
        "(fees structurally uneconomical for usage, e.g. low-volume seasonal where annual fees "
        "rival propane spend – assign even without voiced objection). Qualifiers: rental, "
        "delivery, install, MUC, inspection, monitoring, admin, stack, other — each "
        "slash-joined with ground (e.g. rental/objection, MUC/economics). Over-application "
        "guard: every setup call discloses fees; disclosure alone is NEVER material. Assign "
        "only when pushback or objective economics make fees consequential. Do not assign: "
        "fees for LEAVING (termination, exit → 4D); fee objection where underlying WANT is "
        "tank ownership (→ 4C); concern resolved by accurate explanation. Reasoning anchor: "
        "fees DURING service → 4B. Fees for LEAVING → 4D. Fee complaint masking ownership want "
        "→ 4C."
    ),
    '4C. Commercial model mismatch': (
        "Customer wanted a fundamentally different deal shape than Superior offers – model, "
        "ownership, or commitment length. Route on the customer's underlying WANT, not "
        "complaint wording: complains about rental but wants tank ownership → 4C, not 4B. "
        "Qualifiers: prebuy (fixed volume upfront at locked rate, not offered), ownership "
        "(wanted to own tank, unavailable or conditions made unviable), rate-mechanism "
        "(rejects pricing MODEL – fixed vs variable, capped, indexed, future uncertainty – not "
        "the level), commitment-length (length rejected, e.g. 5yr vs 3yr), supply-terms "
        "(exclusivity or minimum volume resisted), delivery-model (wanted will-call vs "
        "automatic, blocked), other. Do not assign: engaged with offered options and chose "
        "one; explored alternative but accepted after accurate explanation; structure the "
        "offer DID include but rep failed to surface (rep-handling). Reasoning anchor: SHAPE "
        "of the deal → 4C. What BINDS them to it → 4D. Missing product/service → 4E. Rate "
        "NUMBER → 4A."
    ),
    '4D. Contract/transaction mechanics': (
        "A binding contractual mechanic – how the customer is locked in, gets out, or must "
        "transact – was materially unattractive and affected progression. Customer accepts the "
        "deal shape; the barrier is the machinery. Assign when: mechanic stated as too "
        "restrictive; customer requests removal or revision; delays or declines; requires "
        "negotiation or contract revision. Qualifiers: auto-renewal, exit-terms "
        "(early-termination, cancellation, notice periods, equipment removal, "
        "transfer-on-sale), payment-billing (COD, autopay-required-for-rate, budget-plan "
        "gates), escalation-clause (price adjustment clauses, liability), process (e-signature "
        "only, prerequisite gating, documentation demands), complexity (contract rejected as "
        "artifact – too long, fine print), other. Do not assign: mechanics questioned and "
        "accepted; commitment LENGTH (→ 4C); fees during service (→ 4B); prerequisite that is "
        "a commercial model choice (→ 4C). Reasoning anchor: machinery of the contract → 4D. "
        "Shape of the deal → 4C."
    ),
    '4E. Availability/serviceability gap': (
        "Superior could not physically provide the required product, equipment, service, "
        "coverage, or timeline – a genuine supply gap, not a commercial preference. Two tests: "
        "(1) physical, not commercial; (2) genuinely not offered or not providable. Assign "
        "when: location outside service area; product/grade not offered; required tank size or "
        "equipment unavailable; site access, safety, or regulatory limits prevent service; "
        "delivery/install by customer's required date cannot be met (structural or capacity). "
        "Timeline carve-out: service Superior offers but cannot deliver within customer's "
        "REQUIRED timeframe IS a genuine gap → 4E timeline. Qualifiers: service-area, product, "
        "equipment, site, timeline, capability, other. Do not assign: wanted different "
        "delivery model (→ 4C); service gated behind prerequisites (→ 4D process); disliked "
        "version of something offered (→ 4A/4B/4C/4D); gap resolved during call. Reasoning "
        "anchor: Superior CANNOT do it → 4E. COULD but structures differently → 4C/4D."
    ),
    '4F. Promotion ineligibility': (
        "Customer sought a specific promotion, credit, referral discount, or prior offer and "
        "was DENIED or found ineligible. Key signal: access gap or eligibility denial, not a "
        "promo successfully applied. Assign when: expected referral credit but only referrer "
        "qualifies; usage below qualifying volume; owns tank so leased-tank promos don't "
        "apply; references a company rate/offer that cannot be honored today; wanted to stack "
        "promos, denied; chose path foreclosing promo (refused credit check, COD, declined "
        "auto-delivery – policy-gate); promo expired or not yet active. Qualifiers: referral, "
        "threshold, ownership, prior-offer, stacking, policy-gate, timing, other. Boundary: "
        "company offer they CANNOT access → 4F; competitor rate/ad → 4A. Wanted ownership, "
        "blocked → 4C; HAS ownership, promo excludes → 4F. Do not assign: promo applied "
        "successfully; heard of promo, found irrelevant; rep waived fee outside formal promo. "
        "Over-application guard: mention and capture are NEVER findings – only wanted and "
        "denied"
    ),
}

# COMMAND ----------

# MAGIC %md
# MAGIC ### Surface 2 — Instructions (shared framework from master evaluation prompt)
# MAGIC
# MAGIC Sourced verbatim from Sections 1, 3, 6 preamble, and 7 of the master eval
# MAGIC prompt. Per-code definitions are in descriptions above; instructions carry
# MAGIC only the **shared decision framework** (20,000-char `ai_classify` limit).

# COMMAND ----------

INSTRUCTIONS = """\
SECTION 1 – ROLE & MISSION
You are a senior sales operations analyst at Superior Plus Propane. Superior sells both propane and residential oil to residential and commercial customers. You analyze inside-sales call transcripts from sales-qualified-leads (SQLs) to produce coded, audit-grade findings on why opportunities progress, stall, or die. Your output is aggregated across hundreds of opportunities, so consistency and evidence discipline matter more than completeness of flags: a missed borderline flag is acceptable; an unevidenced flag is not. When in doubt, do not assign. 
You code what the transcript shows. You do not infer from outcomes: an objection occurring, a customer remaining dissatisfied, or a deal not converting is never, by itself, evidence for any code. You produce findings, not recommendations – no coaching advice, no strategy commentary, no synthesis beyond the specified output.

SECTION 3 – EVALUATION PROCESS
For each opportunity, in this order:
Read all segments for the opportunity in sequence. A concern raised in an early segment may be resolved, escalated, or confirmed in a later one. Judge the opportunity on its final state, not on any single segment in isolation. 
Identify candidate issues relevant to this module’s codes (Section 6). 
Run the do-not-assign checks first. before coding any candidate issue as a blocker, check whether any exclusion in the code definition applies. an exclusion that fires makes the issue a context-tier row (or routes it), never a blocker.
Determine the disposition (per the module’s disposition set) BEFORE deciding assignment. Assignment follows from disposition, never the reverse.  
Apply the module boundary rule (section 6) to confirm the issue belongs in this module and not another. 
Anchor in evidence (section 4). No evidence, no flag. 
Record the result per the output contract (Section 5). 
Cross-module boundary (applies to every code in this module):
If the customer’s concern DISSOLVED once the rep gave an accurate explanation, the offer was not the blocker – code the issue as disposition ‘resolved’, never as a blocker.  
If the REP’s HANDLING of the issue was the gap (inaccurate, evasive, incomplete explanation), that is a rep-handling matter, out of scope here. Do not assign it here. 
Assign in this module only when the customer understood the offer attributes correctly and still balked, or the attribute factually could not meet their need.

SECTION 6 – CODE DEFINITIONS: OFFER BLOCKERS (4A-4F)
Module exam question
For each code: Did this offer attribute materially block, stall, or degrade the customer’s willingness to proceed — independent of how the rep handled it?
Vocabulary bridge (applies everywhere in this document)
Throughout this document, assign means code an issue as a blocker — disposition hard_blocker or friction. "do not assign" means the issue is not a blocker; it does not mean the issue disappears. a genuine candidate issue that fails the blocker test still receives its table row at the applicable context tier (mention_only, resolved, or latent).
“Do not assign” removes an issue entirely only when it was never a candidate issue (routine question, rep-initiated disclosure), belongs to another code (route it there), or is out of the scope of this module. 
Shared assignment engine (all codes)
A candidate issue codes as a BLOCKER only when ALL three hold: 
Raised as a barrier. The customer (or the facts of the deal) surfaced this attribute as a problem — declining, stalling, demanding a change, or invoking an alternative because of it. A passing remark absorbed into proceeding is not a barrier.
Attributable. The evidence ties the barrier to THIS attribute. General reluctance (“I need to think about it”) is not attributable without the customer connecting it to the attribute.
The attribute, not the explanation. Per the Section 3 boundary rule: if accurate explanation resolved it, or the rep’s handling was the gap, do not assign here.
Dispositions (this module)
hard_blocker — the deal was declined, died, or was made conditional on a change to this attribute that was not granted.
friction — the deal continued, but this attribute caused stall, escalation, a demanded concession, or visible drag on progression.
mention_only — the attribute surfaced as a candidate issue but did not affect progression. Not a blocker; still receives a table row. Expect this to  be the most common outcome.
**resolved** — STRICTLY: the customer’s factual premise was WRONG, accurate explanation corrected it, and the concern dissolved. Resolved is never “the customer accepted the answer” —  if the real premise was corrected (the fee exists, the structure is absent, the rate is real) and they proceeded anyway, that is mention-only or friction, not resolved. Not a blocker; still receives a table row.
- **latent** — HYPOTHESIS tier, never a blocker count. Assign latent only when  ALL THREE hold: (1) an attribute OBJECTIVELY adverse FOR THIS CUSTOMER is  established on the record — adverse relative to their own stated facts, request, or situation, e.g., a computed economics ratio against their stated usage, a rate above their stated current rate, a denied promotion they wanted, or a confirmed unavailability of a product, service, or structure they asked for. A standard fee, rate, or term merely DISCLOSED, with no customer-specific adversity, never qualifies — nor does a merely suspected aversion; (2) the opportunity stalled or ended undetermined; (3) no competing stated cause exists. Never assign latent from absence of enthusiasm or an unexplained stall alone. Include the objective basis (e.g., the computed ratio or the denied request) in the Evidence cell.
insufficient_evidence — transcript quality prevents determination; record with Low confidence.
TIEBREAKER – friction vs. resolved vs. mention_only. Ask in this order: 
Was there anything conceded, waived, credited, or worked around to get past this issue after the customer voiced it? → friction (a concession that follows a voiced issue is friction even when the deal then proceeded). 
Was the customer’s factual premise wrong, and did correcting it end the issue? → resolved 
Did the customer simply accept the accurate answer, with no concession and no drag on progression? → mention_only 
Multiple codes may assign as blockers on one opportunity (attributes are independent). Mark exactly one BLOCKER as Primary — the attribute that most drove the outcome. Context-tier rows never carry Primary.
A customer with no genuine switch intent (benchmarking or price-checking only) has no offer blocker — the offer did not fail; the opportunity was not real. Never stretch a code to cover them; return no assignment. Opportunity legitimacy is assessed elsewhere.
Every code’s qualifier vocabulary includes other as a last resort: use it ONLY when no defined value reasonably fits, and name the specific issue in the evidence. If a defined value plausibly applies, use it — never use other to avoid a routing decision.
The one-question litmus (apply when codes seem to overlap)
Rewrite the customer’s words as a complaint 
About the number on the core price line → 4A
About a bolt-on operating charge → 4B
“I don’t want this DEAL SHAPE” (structural or commitment length) → 4C
“I accept the deal but not what BINDS me to it” → 4D
“I don’t like HOW you require me to transact” (signing method, account or documentation prerequisites) → 4D (process)
“You can’t give me what I NEED” (physical/logistical) → 4E
“I wanted the DEAL you advertised and can’t get it” → 4F
A non-offer fact killed it (credit decline, policy rule, landlord or other third-party control) → NOT coded in this module; return no assignment for the issue. Non-offer blockers are assessed elsewhere.

SECTION 7 – CALIBRATION EXAMPLES
these examples illustrate the assignment threshold, not the range of issues to look for. gaps may involve any attribute and take any form; evaluate every material issue against the rules above, whether or not it resembles an example. Never limit your search to issue types shown here.
Pair 1 — threshold on 4a (rate) 
assign — 4a current-supplier, hard_blocker: customer states “my current supplier’s quote is 12 cents a litre under yours — I can’t justify the switch,” declines the offer, and does not re-engage in the remaining segments. 
NOT A BLOCKER (mention_only row): Customer states “the other guys quoted me a bit less, but honestly their service was terrible,” then proceeds to book installation at the quoted rate.
Pair 2 — threshold on 4c (commercial model) 
assign — 4c prebuy, hard_blocker: customer states “I always pre-buy my winter gallons in august at a locked rate — that’s the only way I buy”; rep confirms SUPERIOR offers only fixed price and variable rate, no pre-buy; customer ends the process on that basis.
NOT A BLOCKER (resolved row): customer asks “do you do pre-buy like my old supplier?”; rep explains SUPERIOR offers fixed price instead and how the rate-lock works; customer says “okay, fixed works for me” and continues to scheduling. 
Pair 3 — threshold on 4e (availability) 
assign — 4e timeline, hard_blocker: customer requires install before october 1 for harvest; rep confirms earliest crew availability is mid-november; customer ends the process on that basis.
Do not assign: customer says “you probably can’t get a truck out to us, we’re pretty remote”; rep checks the address and confirms the route runs weekly; customer proceeds. (speculation resolved — and had the rep failed to check, that would be a rep-handling matter out of scope here, not 4e.)
Pair 4 — threshold on 4f (promotion ineligibility) 
assign — 4f prior-offer, friction: customer states “my neighbour just signed with you at the flyer rate — why can’t i get that?”; rep confirms the promo window closed last month; customer demands escalation and the deal stalls pending an exception.
NOT A BLOCKER (no row – heard and found irrelevant is not a candidate issue):: customer asks “any promotions running right now?”; rep describes the switch credit; customer says “not really my thing” and proceeds at standard terms. (heard, found irrelevant, moved on — not ineligibility.)
END OF OFFER BLOCKER PROMPT —
"""

# COMMAND ----------

# MAGIC %md
# MAGIC ### Config bundling, hashing & registration

# COMMAND ----------

AI_OPTIONS = {
    "version": "2.1",
    "multilabel": "true",
    "enableConfidenceScores": "true",
    "enableRationales": "true",
}

PROMPT_CONFIG = {"labels": LABELS, "instructions": INSTRUCTIONS, "options": AI_OPTIONS}


def config_to_hash(config):
    """Deterministic hash for any prompt config. Uses ensure_ascii=False consistently
    so Unicode chars (en dashes, arrows, curly quotes) always hash the same way."""
    blob = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


CONFIG_HASH = config_to_hash(PROMPT_CONFIG)
print(f"CONFIG_HASH = {CONFIG_HASH}  (changes whenever ANY surface changes)")

# Validate description lengths (ai_classify limit: 1,000 chars per label)
for label, desc in LABELS.items():
    assert len(desc) <= 1000, f"{label}: {len(desc)} chars > 1,000 limit"
    print(f"  {label[:2]}: {len(desc):>4} chars")
assert len(INSTRUCTIONS) <= 20000, f"Instructions: {len(INSTRUCTIONS)} > 20,000 limit"
print(f"  Instructions: {len(INSTRUCTIONS):>5} chars")

# COMMAND ----------

def register_if_changed(name, template, commit_message):
    """Register a new prompt version only if the content has changed."""
    try:
        latest = mlflow.genai.load_prompt(f"prompts:/{name}")
        if latest.template.strip() == template.strip():
            print(f"  ✓ '{name}' already matches — reusing v{latest.version}")
            return latest
    except Exception:
        pass
    reg = mlflow.genai.register_prompt(
        name=name, template=template, commit_message=commit_message,
    )
    print(f"  ✓ Registered '{name}' v{reg.version}: {commit_message}")
    return reg


# Register all three prompts: descriptions, instructions, and the full bundle.
_prompts_to_register = [
    (DESCRIPTIONS_PROMPT_NAME, json.dumps(LABELS, ensure_ascii=False, indent=2), "descriptions"),
    (INSTRUCTIONS_PROMPT_NAME, INSTRUCTIONS, "instructions"),
    (BUNDLE_PROMPT_NAME, json.dumps(PROMPT_CONFIG, ensure_ascii=False, indent=2), "bundle"),
]

PROMPT_VERSIONS = {}
for _name, _template, _label in _prompts_to_register:
    try:
        PROMPT_VERSIONS[_label] = register_if_changed(
            _name, _template, f"{RUN_LABEL} (hash={CONFIG_HASH})",
        )
    except Exception as e:
        PROMPT_VERSIONS[_label] = None
        print(f"  ⚠ {_label}: {type(e).__name__}: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 2 — Load ground truth
# MAGIC
# MAGIC The eval table is an MLflow managed evaluation dataset. We load it via the
# MAGIC managed dataset API for **richer provenance** (the run will link back to the
# MAGIC exact UC table), then parse it for intermediate analysis.

# COMMAND ----------

# Load the managed dataset object (used for provenance in evaluate()).
EVAL_DATASET = None
try:
    import mlflow.genai.datasets
    EVAL_DATASET = mlflow.genai.datasets.get_dataset(EVAL_TABLE)
    _raw_pd = EVAL_DATASET.to_df()
    print(f"✓ Loaded via managed dataset API → provenance will link to {EVAL_TABLE}")
except Exception:
    _raw_pd = spark.table(EVAL_TABLE).toPandas()
    print(f"✓ Loaded via spark.table() fallback (no managed-dataset provenance)")


def _parse_row(row):
    inputs = json.loads(row["inputs"]) if isinstance(row["inputs"], str) else row["inputs"]
    exp = json.loads(row["expectations"]) if isinstance(row["expectations"], str) else row["expectations"]
    codes = json.loads(exp.get("expected_response", "[]"))
    return {
        "opportunity_id": inputs["opportunity_id"],
        "transcript_text": inputs["transcript_text"],
        "expected_codes": codes,
        "expected_set": set(codes),
    }


gt_pd = pd.DataFrame([_parse_row(r) for _, r in _raw_pd.iterrows()])
N_ROWS = len(gt_pd)
print(f"Parsed {N_ROWS} ground-truth rows.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Class balance — inspect before you measure

# COMMAND ----------

n_empty = int((gt_pd["expected_set"].apply(len) == 0).sum())
balance = pd.DataFrame({
    "code": CODE_PREFIXES,
    "positive_rows": [int(gt_pd["expected_set"].apply(lambda s, c=c: c in s).sum()) for c in CODE_PREFIXES],
})
pooled = N_ROWS * len(CODE_PREFIXES)

print(f"Total rows: {N_ROWS}  |  Empty/no-blocker: {n_empty} ({n_empty/N_ROWS:.0%})")
print(f"Pooled label decisions: {pooled}  ← the REAL sample size for micro-F1")
display(balance)

print(f"\n⚠️  NOISE FLOOR: 1 flipped label ≈ {1/pooled:.1%}; "
      f"1 flipped row ≈ ~{len(CODE_PREFIXES)/pooled:.1%} swing in micro-F1.")
for _, r in balance.iterrows():
    if r["positive_rows"] <= 2:
        print(f"   ⚠  {r['code']} has only {r['positive_rows']} positive(s) — per-label F1 is noise.")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 3 — Train / validation / test split (3-way)
# MAGIC
# MAGIC | Split | Purpose | Who sees it |
# MAGIC |-------|---------|-------------|
# MAGIC | **Train** (~70%) | GEPA optimizes against this | GEPA |
# MAGIC | **Validation** (~15%) | Picks the winning candidate | GEPA (used up by selection) |
# MAGIC | **Test** (~15%) | Final honest check | **Nobody until the end** |
# MAGIC
# MAGIC For **manual tuning** we evaluate on the full dataset — splits only matter for GEPA.

# COMMAND ----------

SPLIT_SEED = 42

def _split_hash(opp_id, seed=SPLIT_SEED):
    return int(hashlib.md5(f"{seed}:{opp_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF

gt_pd["split"] = gt_pd["opportunity_id"].apply(
    lambda oid: "test" if _split_hash(oid) < 0.15
    else ("validation" if _split_hash(oid) < 0.30 else "train")
)

train_pd = gt_pd[gt_pd["split"] == "train"].copy()
validation_pd = gt_pd[gt_pd["split"] == "validation"].copy()
test_pd = gt_pd[gt_pd["split"] == "test"].copy()

print(f"Train: {len(train_pd)} | Validation: {len(validation_pd)} | Test: {len(test_pd)}")

for name, df in [("train", train_pd), ("validation", validation_pd), ("test", test_pd)]:
    present = {c for c in CODE_PREFIXES if df["expected_set"].apply(lambda s, c=c: c in s).any()}
    missing = set(CODE_PREFIXES) - present
    status = f"⚠ missing {sorted(missing)}" if missing else f"✓ all {len(CODE_PREFIXES)} labels"
    print(f"  {name}: {status}")

if min(len(train_pd), len(validation_pd), len(test_pd)) < 10:
    print(f"\n  ⚠ Smallest split < 10 rows. GEPA results will be noisy at n={N_ROWS}.")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 4 — Build `ai_classify` SQL & reproducibility cache

# COMMAND ----------

def _sql_str(s):
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


def classify_and_cache(config, config_hash):
    """Run ai_classify and persist results. Idempotent: skips if already cached."""
    have = spark.sql(
        f"SELECT COUNT(*) AS n FROM {CACHE_TABLE} WHERE config_hash = '{config_hash}'"
    ).collect()[0]["n"]
    if have >= N_ROWS:
        print(f"✓ {config_hash} already cached ({have} rows) — skipping.")
        return

    print(f"Running ai_classify for config {config_hash} over {N_ROWS} rows …")
    _gt_spark = spark.createDataFrame(gt_pd[["opportunity_id", "transcript_text"]])
    view_name = f"_eval_inputs_{config_hash[:8]}"
    _gt_spark.createOrReplaceTempView(view_name)
    expr = build_ai_classify_expr("transcript_text", config)

    scored = spark.sql(f"""
      WITH raw AS (SELECT opportunity_id, {expr} AS cls FROM {view_name})
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

    scored.createOrReplaceTempView(f"_scored_{config_hash[:8]}")
    spark.sql(f"DELETE FROM {CACHE_TABLE} WHERE config_hash = '{config_hash}'")
    spark.sql(f"INSERT INTO {CACHE_TABLE} SELECT * FROM _scored_{config_hash[:8]}")
    print(f"✓ Cached {scored.count()} predictions for {config_hash}.")


classify_and_cache(PROMPT_CONFIG, CONFIG_HASH)

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 5 — Shared helpers & deterministic scorers
# MAGIC
# MAGIC Two kinds of measurement:
# MAGIC * **Row-wise** — MLflow `@scorer` functions (visible per-row in the Trace UI)
# MAGIC * **Corpus-wide** — need the whole set; computed in Section 7

# COMMAND ----------

def precision_recall_f1(tp, fp, fn):
    """Compute precision, recall, F1 from counts."""
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def normalize_to_code_set(x):
    """Normalize predictions/expectations to a set of 2-char code prefixes.

    Handles three formats that arise in this notebook:
      - predict_fn output:    {"codes": ["4A", "4B"]}
      - parsed ground truth:  {"expected_codes": ["4A"]}
      - managed dataset raw:  {"expected_response": '["4A"]'}
    """
    if x is None:
        return set()
    if isinstance(x, set):
        return {str(c)[:2] for c in x}
    if isinstance(x, dict):
        # Try each key in priority order
        for key in ("codes", "expected_codes", "expected_response"):
            if key in x:
                v = x[key]
                if isinstance(v, str):
                    v = json.loads(v) if v.startswith("[") else [v]
                return {str(c)[:2] for c in (v or [])}
        return set()
    if isinstance(x, str):
        x = json.loads(x) if x.startswith("[") else [x]
    return {str(c)[:2] for c in (x or [])}


@scorer
def jaccard(outputs, expectations) -> Feedback:
    """Partial-credit set overlap. Empty-vs-empty = 1.0."""
    pred, gold = normalize_to_code_set(outputs), normalize_to_code_set(expectations)
    val = 1.0 if (not pred and not gold) else len(pred & gold) / len(pred | gold)
    return Feedback(value=val, rationale=f"pred={sorted(pred)} gold={sorted(gold)}")


@scorer
def exact_match(outputs, expectations) -> Feedback:
    pred, gold = normalize_to_code_set(outputs), normalize_to_code_set(expectations)
    return Feedback(value=(pred == gold))


@scorer
def abstained_correctly(outputs, expectations) -> Feedback:
    """On rows that SHOULD be empty, did we assign nothing?"""
    pred, gold = normalize_to_code_set(outputs), normalize_to_code_set(expectations)
    if gold:
        return Feedback(value="n/a", rationale="row has a true code")
    return Feedback(value=(len(pred) == 0), rationale=f"predicted {sorted(pred)}")


@scorer
def per_label_hits(outputs, expectations):
    """Per-label TP/FP/FN as individual Feedback objects."""
    pred, gold = normalize_to_code_set(outputs), normalize_to_code_set(expectations)
    feedbacks = []
    for c in CODE_PREFIXES:
        in_pred, in_gold = c in pred, c in gold
        tag = "TP" if (in_gold and in_pred) else "FN" if in_gold else "FP" if in_pred else "TN"
        feedbacks.append(Feedback(name=f"label_{c}", value=(tag in ("TP", "TN")), rationale=tag))
    return feedbacks


@scorer
def boundary_confusion(outputs, expectations) -> Feedback:
    """Flags substitution errors between commonly confused code pairs."""
    pred, gold = normalize_to_code_set(outputs), normalize_to_code_set(expectations)
    confused_pairs = [("4A", "4B"), ("4B", "4C"), ("4C", "4D"), ("4D", "4E")]
    flags = []
    for a, b in confused_pairs:
        if (a in gold and b in pred and a not in pred) or (b in gold and a in pred and b not in pred):
            flags.append(f"{a}↔{b}")
    return Feedback(
        value=0.0 if flags else 1.0,
        rationale=f"boundary confusion: {', '.join(flags)}" if flags else "no boundary confusion",
    )


SCORERS = [jaccard, exact_match, abstained_correctly, per_label_hits, boundary_confusion]

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 6 — Run `mlflow.genai.evaluate()`
# MAGIC
# MAGIC `predict_fn` is a **pure cache lookup** — no LLM call. One run = one prompt variant.

# COMMAND ----------

def make_predict_fn(config_hash):
    """Factory: returns a cache-backed predict function for any config_hash.

    WHY a factory? — the notebook creates predict functions for the baseline config,
    for GEPA-optimized configs, and for the threshold sweep. Without a factory, that
    code was copy-pasted three times.
    """
    rows = spark.sql(f"""
      SELECT opportunity_id, pred_codes, pred_confidences, pred_rationales
      FROM {CACHE_TABLE} WHERE config_hash = '{config_hash}'
    """).collect()
    preds = {r["opportunity_id"]: list(zip(r["pred_codes"] or [], r["pred_confidences"] or [])) for r in rows}
    rats = {r["opportunity_id"]: (r["pred_rationales"] or []) for r in rows}

    @mlflow.trace
    def predict_fn(opportunity_id, transcript_text):
        pairs = preds.get(opportunity_id, [])
        codes = [c[:2] for (c, conf) in pairs if (conf is None or conf >= CONFIDENCE_THRESHOLD)]
        confidences = [conf for (c, conf) in pairs if (conf is None or conf >= CONFIDENCE_THRESHOLD)]
        rationales = rats.get(opportunity_id, [])
        return {"codes": codes, "confidences": confidences, "rationales": rationales}

    return predict_fn, preds


predict_fn, _PREDS = make_predict_fn(CONFIG_HASH)

# Build eval data for managed-dataset passthrough or fallback list.
eval_data_list = [
    {
        "inputs": {"opportunity_id": r.opportunity_id, "transcript_text": r.transcript_text},
        "expectations": {"expected_codes": list(r.expected_codes)},
    }
    for _, r in gt_pd.iterrows()
]

# COMMAND ----------

with mlflow.start_run(run_name=RUN_LABEL) as run:
    mlflow.log_params({
        "config_hash": CONFIG_HASH,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "n_eval_rows": N_ROWS,
        "ai_version": AI_OPTIONS["version"],
        "gepa_phase": GEPA_PHASE,
    })
    for label, ver in PROMPT_VERSIONS.items():
        if ver:
            mlflow.log_params({f"prompt_{label}_version": ver.version})
    mlflow.log_dict(PROMPT_CONFIG, "prompt_config.json")

    eval_result = mlflow.genai.evaluate(
        data=EVAL_DATASET if EVAL_DATASET is not None else eval_data_list,
        predict_fn=predict_fn,
        scorers=SCORERS,
    )
    RUN_ID = run.info.run_id

print(f"\nRun ID: {RUN_ID}")
for k, v in sorted((eval_result.metrics or {}).items()):
    print(f"  {k}: {v}")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 7 — Corpus metrics
# MAGIC
# MAGIC **Micro-F1** is the headline — it pools all `n × 6` label decisions. Per-label
# MAGIC results are **integer TP/FP/FN** because "3 of 4" is honest.

# COMMAND ----------

# MAGIC %md
# MAGIC ### 7a — Build the prediction/truth alignment frame

# COMMAND ----------

pred_pd = pd.DataFrame([
    {"opportunity_id": oid,
     "pred_set": {c[:2] for (c, conf) in pairs if (conf is None or conf >= CONFIDENCE_THRESHOLD)}}
    for oid, pairs in _PREDS.items()
])
merged = gt_pd.merge(pred_pd, on="opportunity_id", how="left")
merged["pred_set"] = merged["pred_set"].apply(lambda s: s if isinstance(s, set) else set())

# COMMAND ----------

# MAGIC %md
# MAGIC ### 7b — Per-label TP / FP / FN

# COMMAND ----------

per_label, micro = [], {"tp": 0, "fp": 0, "fn": 0}
for c in CODE_PREFIXES:
    gold_has = merged["expected_set"].apply(lambda s, c=c: c in s)
    pred_has = merged["pred_set"].apply(lambda s, c=c: c in s)
    tp, fp, fn = int((gold_has & pred_has).sum()), int((~gold_has & pred_has).sum()), int((gold_has & ~pred_has).sum())
    p, r, f1 = precision_recall_f1(tp, fp, fn)
    n_pos = tp + fn
    per_label.append({"code": c, "n_pos": n_pos, "TP": tp, "FP": fp, "FN": fn,
                      "precision": round(p, 2), "recall": round(r, 2), "f1": round(f1, 2),
                      "note": "⚠ n too small" if n_pos <= 2 else ""})
    micro["tp"] += tp; micro["fp"] += fp; micro["fn"] += fn

per_label_df = pd.DataFrame(per_label)
display(per_label_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ### 7c — Corpus headline metrics

# COMMAND ----------

micro_p, micro_r, micro_f1 = precision_recall_f1(micro["tp"], micro["fp"], micro["fn"])
macro_codes = per_label_df[per_label_df["n_pos"] > 2]
macro_f1 = float(macro_codes["f1"].mean()) if len(macro_codes) else 0.0
mean_jaccard = float(merged.apply(
    lambda r: 1.0 if (not r["pred_set"] and not r["expected_set"])
    else len(r["pred_set"] & r["expected_set"]) / len(r["pred_set"] | r["expected_set"]), axis=1
).mean())

abstain_rows = merged[merged["expected_set"].apply(len) == 0]
abstain_acc = float((abstain_rows["pred_set"].apply(len) == 0).mean()) if len(abstain_rows) else float("nan")

excluded = set(per_label_df[per_label_df["n_pos"] <= 2]["code"])
excl_note = f" [excl {sorted(excluded)} n≤2]" if excluded else ""

print("================  HEADLINE  ================")
print(f"  Micro-F1 (headline) : {micro_f1:.2f}   [{micro['tp']}TP {micro['fp']}FP {micro['fn']}FN / {pooled} decisions]")
print(f"  Mean Jaccard        : {mean_jaccard:.2f}")
print(f"  Abstain accuracy    : {abstain_acc:.2f}")
print(f"  Macro-F1 (⚠ noisy)  : {macro_f1:.2f}{excl_note}")
print(f"  NOISE: 1 row ≈ ~{len(CODE_PREFIXES)/pooled:.0%} micro-F1 swing.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 7d — Log corpus metrics to the same run

# COMMAND ----------

with mlflow.start_run(run_id=RUN_ID):
    mlflow.log_metrics({
        "micro_f1": micro_f1, "micro_precision": micro_p, "micro_recall": micro_r,
        "macro_f1": macro_f1, "mean_jaccard": mean_jaccard, "abstain_accuracy": abstain_acc,
    })
    mlflow.log_table(per_label_df, "per_label_metrics.json")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 8 — Error analysis

# COMMAND ----------

_rat_pd = spark.sql(f"""
  SELECT opportunity_id, pred_codes, pred_confidences, pred_rationales
  FROM {CACHE_TABLE} WHERE config_hash = '{CONFIG_HASH}'
""").toPandas()
err = merged.merge(_rat_pd, on="opportunity_id", how="left")


def _bucket(row):
    g, p = row["expected_set"], row["pred_set"]
    if g == p: return "correct"
    if not g and p: return "A. empty-class FP"
    if g and not p: return "B. total MISS"
    if g - p and p - g: return "C. SUBSTITUTION"
    if p - g: return "D. EXTRA code"
    return "E. MISSED one of several"


err["bucket"] = err.apply(_bucket, axis=1)
print("Error distribution:")
print(err["bucket"].value_counts().to_string())

# COMMAND ----------

mistakes = err[err["bucket"] != "correct"][
    ["opportunity_id", "bucket", "expected_codes", "pred_codes", "pred_confidences", "pred_rationales"]
]
display(mistakes)

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 9 — Substitution matrix

# COMMAND ----------

labels_axis = CODE_PREFIXES + ["∅"]
idx = {c: i for i, c in enumerate(labels_axis)}
M = np.zeros((len(labels_axis), len(labels_axis)), dtype=int)
for _, row in err.iterrows():
    missed, added = row["expected_set"] - row["pred_set"], row["pred_set"] - row["expected_set"]
    if not missed and added:
        for a in added: M[idx["∅"], idx[a]] += 1
    elif missed and not added:
        for m in missed: M[idx[m], idx["∅"]] += 1
    else:
        for m in missed:
            for a in added: M[idx[m], idx[a]] += 1

fig, ax = plt.subplots(figsize=(6, 5))
ax.imshow(M, cmap="Oranges")
ax.set_xticks(range(len(labels_axis))); ax.set_xticklabels(labels_axis)
ax.set_yticks(range(len(labels_axis))); ax.set_yticklabels(labels_axis)
ax.set_xlabel("predicted instead"); ax.set_ylabel("true code")
ax.set_title("Substitution matrix (true → predicted-instead)")
for i in range(len(labels_axis)):
    for j in range(len(labels_axis)):
        if M[i, j]: ax.text(j, i, M[i, j], ha="center", va="center")
fig.tight_layout()
display(fig)

with mlflow.start_run(run_id=RUN_ID):
    mlflow.log_figure(fig, "substitution_matrix.png")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 10 — Decision guide + confidence threshold sweep
# MAGIC
# MAGIC | Error signature | Lever |
# MAGIC |---|---|
# MAGIC | **C: Substitution** | Edit **DESCRIPTIONS** contrastively, in pairs |
# MAGIC | **A: Empty-class FP** | Edit **INSTRUCTIONS** (raise evidence bar) |
# MAGIC | **B/E: Misses** | Edit **INSTRUCTIONS** or lower threshold |
# MAGIC | **Systematic** | **Threshold** sweep first — it's free |

# COMMAND ----------

# The merge in Section 8 brings pred_codes / pred_confidences from the cache table.
# No suffix collision because `merged` only has `pred_set`, not `pred_codes`.
err["_raw_codes"] = err["pred_codes"]
err["_raw_confs"] = err["pred_confidences"]

sweep_rows = []
for tau in [0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9]:
    tp = fp = fn = correct_abstain = total_abstain = 0
    for _, row in err.iterrows():
        raw_codes = row["_raw_codes"] if row["_raw_codes"] is not None else []
        raw_confs = row["_raw_confs"] if row["_raw_confs"] is not None else []
        pset = {str(c)[:2] for c, conf in zip(raw_codes, raw_confs) if conf is None or conf >= tau}
        gset = row["expected_set"]
        tp += len(pset & gset); fp += len(pset - gset); fn += len(gset - pset)
        if not gset:
            total_abstain += 1; correct_abstain += int(len(pset) == 0)
    _, _, f1 = precision_recall_f1(tp, fp, fn)
    sweep_rows.append({"tau": tau, "micro_f1": round(f1, 2),
                       "abstain_acc": round(correct_abstain / total_abstain, 2) if total_abstain else None})

display(pd.DataFrame(sweep_rows))
print("Pick the smallest τ that holds micro-F1 near its peak while improving abstain accuracy.")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 11 — Programmatic run comparison

# COMMAND ----------

_all_runs = mlflow.search_runs(order_by=["start_time DESC"])
if len(_all_runs) > 0:
    _metric_cols = sorted(c for c in _all_runs.columns if c.startswith("metrics."))
    _param_cols = [c for c in ["params.config_hash", "params.confidence_threshold",
                               "params.gepa_phase", "params.n_eval_rows"] if c in _all_runs.columns]
    display(_all_runs[["run_id"] + _param_cols + _metric_cols].head(20))
else:
    print("No runs found yet.")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 12 — GEPA automated prompt optimization
# MAGIC
# MAGIC GEPA evolves prompt text via a genetic-Pareto optimizer. The `gepa_phase` widget
# MAGIC controls which surface(s) are optimized:
# MAGIC
# MAGIC | Phase | Optimizes | Frozen | Notes |
# MAGIC |-------|-----------|--------|-------|
# MAGIC | `instructions` | Instructions string | Descriptions | **Recommended first** — natural language, no structural constraints |
# MAGIC | `descriptions` | 6 label descriptions (JSON) | Instructions | GEPA must preserve valid JSON with exact keys ≤1000 chars each |
# MAGIC | `joint` | Both | Nothing | Largest search space; run after individual phases plateau |
# MAGIC
# MAGIC **Budget**: `max_metric_calls=300` gives GEPA ~20 full-dataset evaluations
# MAGIC to explore.  The diagnostic counter `_gepa_call_log` prints after optimization
# MAGIC to reveal whether mutations are failing validation (JSON parse, key mismatch,
# MAGIC length overflow) vs. simply scoring worse than the seed.
# MAGIC
# MAGIC All phases share the same orchestration function below — the only difference is
# MAGIC which prompt URI(s) are passed to `optimize_prompts()`.

# COMMAND ----------

if not RUN_GEPA:
    print("GEPA is OFF (set `run_gepa` to 'true').")

# COMMAND ----------

if RUN_GEPA:
    from mlflow.genai.optimize import GepaPromptOptimizer
    import hashlib

    # --- Row-level GEPA scorer --------------------------------------------------------
    # NOTE: GEPA averages this per-row score — that is example-averaged F1, which
    # approximates but is NOT identical to corpus micro-F1.
    # Rich rationales help the reflection model understand what went wrong.
    @scorer
    def gepa_row_f1(outputs, expectations) -> Feedback:
        # If the predict_fn returned an error, score 0 with the error as rationale.
        if isinstance(outputs, dict) and outputs.get("error"):
            return Feedback(value=0.0, rationale=f"PREDICT ERROR: {outputs['error']}")

        pred = normalize_to_code_set(outputs)
        gold = normalize_to_code_set(expectations)
        tp, fp, fn = len(pred & gold), len(pred - gold), len(gold - pred)
        _, _, f1 = precision_recall_f1(tp, fp, fn)

        # Build a diagnostic rationale the reflection model can learn from
        parts = [f"F1={f1:.2f}"]
        if pred == gold:
            parts.append("EXACT MATCH")
        else:
            if pred - gold:
                parts.append(f"FALSE POS: {sorted(pred - gold)}")
            if gold - pred:
                parts.append(f"FALSE NEG: {sorted(gold - pred)}")
        parts.append(f"expected={sorted(gold)} predicted={sorted(pred)}")
        return Feedback(value=f1, rationale=" | ".join(parts))

    # --- Build train / validation / test data for GEPA --------------------------------
    def _split_to_gepa_data(df):
        return [
            {"inputs": {"opportunity_id": r.opportunity_id, "transcript_text": r.transcript_text},
             "expectations": {"expected_codes": list(r.expected_codes)}}
            for _, r in df.iterrows()
        ]

    train_data = _split_to_gepa_data(train_pd)
    validation_data = _split_to_gepa_data(validation_pd)
    test_data = _split_to_gepa_data(test_pd)

    print(f"GEPA splits: {len(train_data)} train, {len(validation_data)} validation, {len(test_data)} test")

# COMMAND ----------

if RUN_GEPA:
    # Keep a reference copy of the original label keys for validation
    _EXPECTED_LABEL_KEYS = set(LABELS.keys())

    # --- Diagnostic counter for GEPA mutations ----------------------------------------
    _gepa_call_log = {"total": 0, "desc_parse_fail": 0, "desc_key_mismatch": 0,
                      "desc_too_long": 0, "instr_too_long": 0, "sql_error": 0, "ok": 0}

    def _validate_descriptions(raw_template):
        """Parse and validate a GEPA-mutated descriptions template.
        Returns (labels_dict, None) on success or (None, error_string) on failure."""
        # Strip common LLM artifacts (markdown code fences)
        text = raw_template.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]  # remove opening fence line
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            labels = json.loads(text)
        except json.JSONDecodeError as e:
            _gepa_call_log["desc_parse_fail"] += 1
            return None, f"JSON parse error: {e}"

        if not isinstance(labels, dict) or len(labels) != 6:
            _gepa_call_log["desc_parse_fail"] += 1
            return None, f"Expected dict with 6 keys, got {type(labels).__name__} with {len(labels) if isinstance(labels, dict) else '?'} entries"

        # Validate keys match exactly (GEPA may rename them)
        if set(labels.keys()) != _EXPECTED_LABEL_KEYS:
            _gepa_call_log["desc_key_mismatch"] += 1
            missing = _EXPECTED_LABEL_KEYS - set(labels.keys())
            extra = set(labels.keys()) - _EXPECTED_LABEL_KEYS
            return None, f"Key mismatch — missing: {missing}, unexpected: {extra}"

        # Validate per-label length
        for k, v in labels.items():
            if not isinstance(v, str) or len(v) == 0:
                return None, f"Label '{k}' must be a non-empty string"
            if len(v) > 1000:
                _gepa_call_log["desc_too_long"] += 1
                return None, f"Label '{k}' has {len(v)} chars (max 1000)"

        return labels, None

    def _validate_instructions(text):
        """Validate a GEPA-mutated instructions string.
        Returns (instructions, None) on success or (None, error_string) on failure."""
        if not isinstance(text, str) or not text.strip():
            return None, "Instructions must be non-empty text"
        if len(text) > 20_000:
            _gepa_call_log["instr_too_long"] += 1
            return None, f"Instructions exceed limit: {len(text)} > 20000 chars"
        return text, None

    def _descriptions_predict_fn(opportunity_id, transcript_text):
        """GEPA predict_fn for descriptions phase: loads GEPA-mutated descriptions."""
        _gepa_call_log["total"] += 1
        prompt = mlflow.genai.load_prompt(PROMPT_VERSIONS["descriptions"].uri)
        labels, err = _validate_descriptions(prompt.template)
        if err:
            return {"codes": [], "error": err}
        config = {"labels": labels, "instructions": INSTRUCTIONS, "options": AI_OPTIONS}
        return _gepa_classify_single(config, opportunity_id, transcript_text)

    def _instructions_predict_fn(opportunity_id, transcript_text):
        """GEPA predict_fn for instructions phase: loads GEPA-mutated instructions."""
        _gepa_call_log["total"] += 1
        prompt = mlflow.genai.load_prompt(PROMPT_VERSIONS["instructions"].uri)
        instructions, err = _validate_instructions(prompt.template)
        if err:
            return {"codes": [], "error": err}
        config = {"labels": LABELS, "instructions": instructions, "options": AI_OPTIONS}
        return _gepa_classify_single(config, opportunity_id, transcript_text)

    def _joint_predict_fn(opportunity_id, transcript_text):
        """GEPA predict_fn for joint phase: loads both GEPA-mutated prompts."""
        _gepa_call_log["total"] += 1
        desc_prompt = mlflow.genai.load_prompt(PROMPT_VERSIONS["descriptions"].uri)
        instr_prompt = mlflow.genai.load_prompt(PROMPT_VERSIONS["instructions"].uri)
        labels, err = _validate_descriptions(desc_prompt.template)
        if err:
            return {"codes": [], "error": err}
        instructions, err2 = _validate_instructions(instr_prompt.template)
        if err2:
            return {"codes": [], "error": err2}
        config = {"labels": labels, "instructions": instructions, "options": AI_OPTIONS}
        return _gepa_classify_single(config, opportunity_id, transcript_text)

    def _gepa_classify_single(config, opportunity_id, transcript_text):
        """Shared: run ai_classify for one row and return normalized codes."""
        try:
            expr = build_ai_classify_expr("transcript_text", config)
            view = f"_gepa_{uuid.uuid4().hex[:8]}"
            spark.createDataFrame([(transcript_text,)], ["transcript_text"]).createOrReplaceTempView(view)
            result = spark.sql(f"""
                SELECT transform(
                    ({expr}):response::ARRAY<STRUCT<value:STRING,confidence_score:DOUBLE,rationale:STRING>>,
                    x -> x.value
                ) AS pred_codes FROM {view}
            """).collect()[0]
            _gepa_call_log["ok"] += 1
            return {"codes": [c[:2] for c in (result.pred_codes or [])]}
        except Exception as e:
            _gepa_call_log["sql_error"] += 1
            return {"codes": [], "error": f"SQL error: {e}"}

# COMMAND ----------

if RUN_GEPA:
    # --- Determine which prompt URIs to optimize based on phase -----------------------
    phase_config = {
        "descriptions": {
            "uris": [PROMPT_VERSIONS["descriptions"].uri],
            "predict_fn": _descriptions_predict_fn,
        },
        "instructions": {
            "uris": [PROMPT_VERSIONS["instructions"].uri],
            "predict_fn": _instructions_predict_fn,
        },
        "joint": {
            "uris": [PROMPT_VERSIONS["descriptions"].uri, PROMPT_VERSIONS["instructions"].uri],
            "predict_fn": _joint_predict_fn,
        },
    }

    pc = phase_config[GEPA_PHASE]
    print(f"GEPA phase: {GEPA_PHASE}")
    print(f"  Optimizing: {[u.split('/')[-1] for u in pc['uris']]}")
    print(f"  Frozen: {'nothing' if GEPA_PHASE == 'joint' else 'descriptions' if GEPA_PHASE == 'instructions' else 'instructions'}")

    try:
        # Budget: 50 metric calls was far too small. With n=14 rows, the seed
        # evaluation alone consumes ~14 calls, leaving almost nothing for
        # candidate exploration.  300 calls ≈ ~20 full-dataset evaluations,
        # giving GEPA meaningful room to search.
        # reflection_minibatch_size=3 reduces per-iteration cost so the
        # optimizer can attempt more mutations within the budget.
        gepa_result = mlflow.genai.optimize_prompts(
            predict_fn=pc["predict_fn"],
            train_data=train_data,
            prompt_uris=pc["uris"],
            optimizer=GepaPromptOptimizer(
                reflection_model="databricks:/databricks-claude-sonnet-5",
                max_metric_calls=300,
                display_progress_bar=True,
            ),
            scorers=[gepa_row_f1],
        )

        # --- Diagnostic summary of GEPA predict calls --------------------------------
        print(f"\n--- GEPA predict-fn diagnostics ---")
        for k, v in sorted(_gepa_call_log.items()):
            print(f"  {k}: {v}")

        print(f"\nInitial score: {gepa_result.initial_eval_score}")
        print(f"Final score:   {gepa_result.final_eval_score}")

        # Determine the optimized config
        if GEPA_PHASE == "descriptions":
            opt_labels = json.loads(gepa_result.optimized_prompts[0].template)
            opt_config = {"labels": opt_labels, "instructions": INSTRUCTIONS, "options": AI_OPTIONS}
        elif GEPA_PHASE == "instructions":
            opt_instr = gepa_result.optimized_prompts[0].template
            opt_config = {"labels": LABELS, "instructions": opt_instr, "options": AI_OPTIONS}
        else:  # joint
            opt_labels = json.loads(gepa_result.optimized_prompts[0].template)
            opt_instr = gepa_result.optimized_prompts[1].template
            opt_config = {"labels": opt_labels, "instructions": opt_instr, "options": AI_OPTIONS}

        opt_hash = config_to_hash(opt_config)
        classify_and_cache(opt_config, opt_hash)

        # --- Evaluate on UNTOUCHED test split -----------------------------------------
        opt_predict_fn, _ = make_predict_fn(opt_hash)

        with mlflow.start_run(run_name=f"{RUN_LABEL}_gepa_{GEPA_PHASE}_test") as gepa_run:
            mlflow.log_params({
                "config_hash": opt_hash, "source": f"GEPA-{GEPA_PHASE}",
                "split": "test (untouched)", "n_eval_rows": len(test_data),
                "gepa_initial": gepa_result.initial_eval_score,
                "gepa_final": gepa_result.final_eval_score,
            })
            mlflow.log_dict(opt_config, "prompt_config.json")
            gepa_eval = mlflow.genai.evaluate(data=test_data, predict_fn=opt_predict_fn, scorers=SCORERS)

        print(f"\n{'='*50}")
        print(f"  GEPA TEST-SPLIT EVALUATION (untouched)")
        print(f"{'='*50}")
        for k, v in sorted((gepa_eval.metrics or {}).items()):
            print(f"  {k}: {v}")

    except Exception as e:
        print(f"⚠ GEPA failed: {type(e).__name__}: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 13 — Promote the winning prompt

# COMMAND ----------

_prompts_to_promote = [
    (DESCRIPTIONS_PROMPT_NAME, "descriptions"),
    (INSTRUCTIONS_PROMPT_NAME, "instructions"),
    (BUNDLE_PROMPT_NAME, "bundle"),
]

for _name, _label in _prompts_to_promote:
    ver = PROMPT_VERSIONS.get(_label)
    if ver:
        try:
            mlflow.genai.set_prompt_alias(name=_name, alias="production", version=ver.version)
            print(f"✓ {_name} v{ver.version} → @production")
        except Exception as e:
            print(f"⚠ {_name}: {type(e).__name__}: {e}")
    else:
        print(f"  {_label}: no version to promote")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC ## Section 14 — Next steps
# MAGIC
# MAGIC ### 1. Grow the labeled set
# MAGIC The eval table is a managed dataset — growth is one call:
# MAGIC ```python
# MAGIC ds = mlflow.genai.datasets.get_dataset("catalog.schema.your_table")
# MAGIC ds.merge_records([...])
# MAGIC ```
# MAGIC Target: 200–400 rows for GEPA, 800+ for production-grade.
# MAGIC
# MAGIC ### 2. Pipeline integration
# MAGIC Future state: the pipeline reads from the `@production` alias:
# MAGIC ```python
# MAGIC prompt = mlflow.genai.load_prompt(f"prompts:/{BUNDLE_PROMPT_NAME}@production")
# MAGIC config = json.loads(prompt.template)
# MAGIC ```
# MAGIC
# MAGIC ### 3. Stochasticity check
# MAGIC Re-run one config 3–5× (clear cache first) to see micro-F1 wobble.
# MAGIC
# MAGIC ### 4. The qualifier layer
# MAGIC `gold_findings_raw` runs a finer qualifier per code (4A → current-supplier, etc.).
# MAGIC Same eval harness generalizes — swap labels and build a parallel eval table.
