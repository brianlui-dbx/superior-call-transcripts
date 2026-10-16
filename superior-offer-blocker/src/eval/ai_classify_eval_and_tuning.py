# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# MAGIC %md
# MAGIC # Evaluating & Tuning the `ai_classify` Offer-Blocker Classifier
# MAGIC
# MAGIC This single notebook teaches
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
# MAGIC | **Setup** | 0–1 | Parameters, prompt config, **register prompts in Prompt Registry** |
# MAGIC | **Data** | 2–3 | Load managed eval dataset, inspect class balance, train/validation/test split |
# MAGIC | **Score** | 4–7 | Build SQL, cache predictions, run `mlflow.genai.evaluate()`, corpus metrics |
# MAGIC | **Diagnose** | 8–10 | Error analysis, substitution matrix, decision guide + threshold sweep |
# MAGIC | **Compare** | 11 | Programmatic side-by-side of all runs |
# MAGIC | **Optimize** | 12a–12c | (Optional) GEPA automated prompt optimization — phase-gated: descriptions / instructions / joint |
# MAGIC | **Ship** | 13–14 | Conditional promotion + next steps |
# MAGIC
# MAGIC The notebook is **idempotent**: run it top-to-bottom any number of times and you
# MAGIC get the same experiment state. Expensive `ai_classify` calls are cached by a
# MAGIC hash of the prompt config, so re-runs are free *and* deterministic.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 0 — Setup & parameters

# COMMAND ----------

# MAGIC %pip install -q -U "mlflow[databricks]>=3.5" "gepa>=0.0.26"
# MAGIC %restart_python

# COMMAND ----------

# Widgets = the notebook's parameters. Defaults let you run interactively; a job can
# override them. Changing a widget and re-running is how you point this at new data.
dbutils.widgets.text("catalog", "dbw_brlui_stable", "Catalog")
dbutils.widgets.text("schema", "call_transcripts_poc", "Schema")
dbutils.widgets.text("eval_table", "code_classification_eval_dataset", "Ground-truth eval dataset")
dbutils.widgets.text("experiment_path", "", "MLflow experiment path (blank = notebook default)")
dbutils.widgets.text("run_label", "baseline_v1", "Human name for THIS prompt variant")
dbutils.widgets.text("confidence_threshold", "0.0", "Keep labels with confidence >= this")
dbutils.widgets.dropdown("run_gepa", "true", ["false", "true"], "Run GEPA automated optimization?")
dbutils.widgets.dropdown(
    "gepa_phase", "joint",
    ["descriptions", "instructions", "joint"],
    "GEPA phase: which surface(s) to optimize",
)

# COMMAND ----------

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
EVAL_TABLE = f"{CATALOG}.{SCHEMA}.{dbutils.widgets.get('eval_table')}"
CACHE_TABLE = f"{CATALOG}.{SCHEMA}.ai_classify_eval_cache_v3"
DESCRIPTIONS_PROMPT_NAME = f"{CATALOG}.{SCHEMA}.offer_blocker_descriptions"
INSTRUCTIONS_PROMPT_NAME = f"{CATALOG}.{SCHEMA}.offer_blocker_instructions"
BUNDLE_PROMPT_NAME = f"{CATALOG}.{SCHEMA}.offer_blocker_ai_classify_prompt"
RUN_LABEL = dbutils.widgets.get("run_label")
CONFIDENCE_THRESHOLD = float(dbutils.widgets.get("confidence_threshold"))
RUN_GEPA = dbutils.widgets.get("run_gepa") == "true"
GEPA_PHASE = dbutils.widgets.get("gepa_phase")

print(f"Ground truth       : {EVAL_TABLE}")
print(f"Cache table        : {CACHE_TABLE}")
print(f"Descriptions prompt: {DESCRIPTIONS_PROMPT_NAME}")
print(f"Instructions prompt: {INSTRUCTIONS_PROMPT_NAME}")
print(f"Run label          : {RUN_LABEL}")
print(f"Confidence τ       : {CONFIDENCE_THRESHOLD}")
print(f"Run GEPA           : {RUN_GEPA}  (phase: {GEPA_PHASE})")

# COMMAND ----------

import json
import hashlib
import uuid
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
# MAGIC register each surface in the **MLflow Prompt Registry** — a Unity-Catalog-backed
# MAGIC version store for prompt templates.
# MAGIC
# MAGIC We maintain **two registered prompts** so GEPA can optimize each surface
# MAGIC independently:
# MAGIC
# MAGIC | Prompt | Content | GEPA touches it? |
# MAGIC |--------|---------|------------------|
# MAGIC | `offer_blocker_descriptions` | JSON dict of 6 label descriptions | Yes (phase `descriptions` or `joint`) |
# MAGIC | `offer_blocker_instructions` | Free-text instructions string | Yes (phase `instructions` or `joint`) |
# MAGIC
# MAGIC Plus a **bundle prompt** (`offer_blocker_ai_classify_prompt`) that snapshots
# MAGIC the full `(descriptions + instructions + options)` config for reproducibility.
# MAGIC
# MAGIC The iteration loop becomes:
# MAGIC 1. **Edit** one surface below (descriptions *or* instructions — never both at once).
# MAGIC 2. **Register** new prompt versions (the cell below does this automatically).
# MAGIC 3. **Evaluate** by re-running the notebook with a new `run_label`.
# MAGIC 4. **Compare** runs side-by-side in the Experiments UI.
# MAGIC 5. **Promote** the winner to the `"production"` alias (Section 13).
# MAGIC
# MAGIC > Keep the baseline below **byte-for-byte identical to production** so your first
# MAGIC > number reflects reality.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Surface 1 — Label descriptions
# MAGIC
# MAGIC Each description is maxed out at ~1,000 characters to give `ai_classify` the
# MAGIC richest possible routing signal. The structure for each label:
# MAGIC - **What it means** (the core definition)
# MAGIC - **Assign when** (key signals & sub-types)
# MAGIC - **Do NOT assign** (boundary exclusions → the other code)
# MAGIC - **Boundary rule** (the litmus test separating adjacent codes)
# MAGIC
# MAGIC These descriptions are distilled from the **master evaluation prompt rubric**
# MAGIC (`examples/Module 2 - Offer Blocker AI Prompt v6.docx`, Section 6) — the
# MAGIC authoritative source of truth for all code definitions, qualifiers, and boundary
# MAGIC rules. Each description preserves the docx's exact language as much as possible
# MAGIC while staying within the 1,000-character limit.

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
# MAGIC The instructions string is the global directive that governs *when to assign
# MAGIC anything at all*. It is sourced **verbatim** from the master evaluation prompt
# MAGIC document (`examples/Module 2 - Offer Blocker AI Prompt v6.docx`), specifically:
# MAGIC
# MAGIC - **Section 1** — Role & Mission (who you are, evidence discipline)
# MAGIC - **Section 3** — Evaluation Process (how to read and classify)
# MAGIC - **Section 6 preamble** — Shared assignment engine, dispositions, tiebreaker,
# MAGIC   boundary litmus test (the *framework* — NOT the per-code definitions, which
# MAGIC   are already in the label descriptions above)
# MAGIC - **Section 7** — Calibration Examples (threshold-setting pairs per code)
# MAGIC
# MAGIC > **Why not the full Section 6?** `ai_classify` has a **20,000-character limit**
# MAGIC > on instructions. The full rubric is ~32K chars. The per-code definitions
# MAGIC > (~22K chars) are already expressed in the label descriptions — including them
# MAGIC > in instructions too would be redundant AND exceed the limit. The cleaner design:
# MAGIC > **descriptions = per-code routing rules; instructions = shared framework.**
# MAGIC
# MAGIC This is the **authoritative source of truth**; GEPA can evolve it from this
# MAGIC baseline.

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

# --- ai_classify options (part of the versioned config) --------------------------------
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

# Quick sanity: check description lengths against ai_classify's 1,000-char limit.
for label_key, desc in LABELS.items():
    if len(desc) > 1000:
        print(f"  ⚠ {label_key[:2]} description is {len(desc)} chars (limit 1,000) — TRUNCATE!")
    else:
        print(f"  ✓ {label_key[:2]} description: {len(desc)} chars")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Register configs in the Prompt Registry
# MAGIC
# MAGIC Each prompt variant becomes a **version** in the registry. The notebook checks
# MAGIC whether the latest version already matches (idempotency) — if so, it reuses it
# MAGIC rather than creating a duplicate.
# MAGIC
# MAGIC We register **three** prompts:
# MAGIC 1. `offer_blocker_descriptions` — just the JSON dict of label descriptions (GEPA surface 1)
# MAGIC 2. `offer_blocker_instructions` — just the instructions string (GEPA surface 2)
# MAGIC 3. `offer_blocker_ai_classify_prompt` — the full bundle (for reproducibility & promotion)

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


# --- Register descriptions prompt (GEPA surface 1) ------------------------------------
_desc_template = json.dumps(LABELS, ensure_ascii=False, indent=2)
try:
    DESC_PROMPT_VERSION = _register_if_changed(
        name=DESCRIPTIONS_PROMPT_NAME,
        template=_desc_template,
        commit_message=f"{RUN_LABEL} descriptions (config_hash={CONFIG_HASH})",
    )
except Exception as e:
    DESC_PROMPT_VERSION = None
    print(f"(Descriptions prompt unavailable: {type(e).__name__}: {e})")

# --- Register instructions prompt (GEPA surface 2) ------------------------------------
try:
    INSTR_PROMPT_VERSION = _register_if_changed(
        name=INSTRUCTIONS_PROMPT_NAME,
        template=INSTRUCTIONS,
        commit_message=f"{RUN_LABEL} instructions (config_hash={CONFIG_HASH})",
    )
except Exception as e:
    INSTR_PROMPT_VERSION = None
    print(f"(Instructions prompt unavailable: {type(e).__name__}: {e})")

# --- Register the FULL bundle (descriptions + instructions + options) ------------------
_config_template = json.dumps(PROMPT_CONFIG, ensure_ascii=False, indent=2)
try:
    BUNDLE_PROMPT_VERSION = _register_if_changed(
        name=BUNDLE_PROMPT_NAME,
        template=_config_template,
        commit_message=f"{RUN_LABEL} (config_hash={CONFIG_HASH})",
    )
except Exception as e:
    BUNDLE_PROMPT_VERSION = None
    print(f"(Bundle prompt unavailable: {type(e).__name__}: {e})")
    print("Continuing without Prompt Registry — config is still hashed and logged as a run artifact.")

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
# MAGIC assessment.
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

def classify_and_cache(config, config_hash, input_df=None):
    """Run ai_classify and persist results. Idempotent: skips if already cached.

    Parameters
    ----------
    config : dict       — the full prompt config (labels + instructions + options)
    config_hash : str   — 16-char hex hash of the config
    input_df : pd.DataFrame, optional — if None, uses the full gt_pd
    """
    if input_df is None:
        input_df = gt_pd
    n_input = len(input_df)

    have = spark.sql(
        f"SELECT COUNT(*) AS n FROM {CACHE_TABLE} WHERE config_hash = '{config_hash}'"
    ).collect()[0]["n"]
    if have >= n_input:
        print(f"✓ config {config_hash} already cached ({have} rows) — skipping LLM calls.")
        return

    print(f"Running ai_classify for config {config_hash} over {n_input} rows …")
    # Use a unique temp view name to avoid concurrency hazards (important for GEPA)
    view_name = f"_eval_inputs_{config_hash[:8]}"
    _gt_spark = spark.createDataFrame(input_df[["opportunity_id", "transcript_text"]])
    _gt_spark.createOrReplaceTempView(view_name)
    expr = build_ai_classify_expr("transcript_text", config)

    scored = spark.sql(f"""
      WITH raw AS (
        SELECT opportunity_id, {expr} AS cls FROM {view_name}
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

    scored.createOrReplaceTempView(f"_scored_{config_hash[:8]}")
    spark.sql(f"DELETE FROM {CACHE_TABLE} WHERE config_hash = '{config_hash}'")
    spark.sql(f"INSERT INTO {CACHE_TABLE} SELECT * FROM _scored_{config_hash[:8]}")
    print(f"✓ cached {scored.count()} predictions for config {config_hash}.")

classify_and_cache(PROMPT_CONFIG, CONFIG_HASH)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5 — Deterministic scorers
# MAGIC
# MAGIC We have ground truth → compare sets with plain Python. **No LLM judge is needed.**
# MAGIC
# MAGIC Two kinds of measurement (knowing which is which is a core lesson):
# MAGIC * **Row-wise** (Jaccard, exact-match, abstain, per-label hits, boundary confusion)
# MAGIC   — MLflow `@scorer` functions; visible per-row in the Trace UI.
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
    for c in CODE_PREFIXES:
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


# --- Boundary confusion scorer --------------------------------------------------------
# Adjacent-code pairs where description leakage causes the most damage. When the model
# predicts one of a pair but the gold has the other, that is a BOUNDARY error — a signal
# to edit the descriptions contrastively rather than touch instructions.
_BOUNDARY_PAIRS = [("4A", "4C"), ("4B", "4C"), ("4B", "4D"), ("4C", "4D"), ("4C", "4E"), ("4D", "4E")]

@scorer
def boundary_confusion(outputs, expectations) -> Feedback:
    """Penalize boundary errors between adjacent codes.
    Returns 1.0 if no boundary confusion, 0.0 if any boundary pair is crossed.
    A boundary error is: gold has code X, pred has code Y (or vice versa),
    where (X,Y) is a known confusable pair."""
    pred, gold = _as_set(outputs), _as_set(expectations.get("expected_codes"))
    missed = gold - pred  # codes we should have assigned but didn't
    added = pred - gold   # codes we assigned but shouldn't have
    boundary_errors = []
    for a, b in _BOUNDARY_PAIRS:
        # Check if we swapped one for the other
        if (a in missed and b in added) or (b in missed and a in added):
            boundary_errors.append(f"{a}↔{b}")
    if boundary_errors:
        return Feedback(value=0.0, rationale=f"boundary confusion: {', '.join(boundary_errors)}")
    return Feedback(value=1.0, rationale="no boundary confusion")


SCORERS = [jaccard, exact_match, abstained_correctly, per_label_hits, boundary_confusion]

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
        "gepa_phase": GEPA_PHASE,
        "source": "manual",
    })
    if BUNDLE_PROMPT_VERSION:
        mlflow.log_params({
            "prompt_registry_name": BUNDLE_PROMPT_NAME,
            "prompt_registry_version": BUNDLE_PROMPT_VERSION.version,
        })
    if DESC_PROMPT_VERSION:
        mlflow.log_params({"descriptions_prompt_version": DESC_PROMPT_VERSION.version})
    if INSTR_PROMPT_VERSION:
        mlflow.log_params({"instructions_prompt_version": INSTR_PROMPT_VERSION.version})
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

# Boundary confusion rate (new metric).
n_boundary = 0
for _, row in merged.iterrows():
    missed = row["expected_set"] - row["pred_set"]
    added = row["pred_set"] - row["expected_set"]
    for a, b in _BOUNDARY_PAIRS:
        if (a in missed and b in added) or (b in missed and a in added):
            n_boundary += 1
            break  # count each row at most once
boundary_rate = n_boundary / N_ROWS if N_ROWS else 0.0

display(per_label_df)
excluded_labels = set(per_label_df[per_label_df["n_pos"] <= 2]["code"])
excl_note = f" [excludes {sorted(excluded_labels)} n≤2]" if excluded_labels else ""

print("\n================  HEADLINE  ================")
print(f"  Micro-F1 (headline) : {micro_f1:.2f}   [pooled {micro['tp']}TP {micro['fp']}FP {micro['fn']}FN over {pooled} decisions]")
print(f"  Mean Jaccard        : {mean_jaccard:.2f}")
print(f"  Abstain accuracy    : {abstain_acc:.2f}   [{int((abstain_rows['pred_set'].apply(len)==0).sum())} of {len(abstain_rows)} empty rows correct]")
print(f"  Macro-F1 (⚠ noisy)  : {macro_f1:.2f}  {excl_note}")
print(f"  Boundary confusion  : {boundary_rate:.0%}  ({n_boundary} of {N_ROWS} rows have a boundary swap)")
print(f"  Exact-match         : see MLflow run (sanity stat only — brutal for multilabel)")
print(f"\n  NOISE FLOOR: 1 row flip ≈ ~{len(CODE_PREFIXES)/pooled:.0%} micro-F1."
      " Do NOT declare a winner on a sub-1-row move.")

# Log corpus metrics into the SAME run.
with mlflow.start_run(run_id=RUN_ID):
    mlflow.log_metrics({
        "micro_f1": micro_f1, "micro_precision": micro_p, "micro_recall": micro_r,
        "macro_f1": macro_f1, "mean_jaccard": mean_jaccard, "abstain_accuracy": abstain_acc,
        "boundary_confusion_rate": boundary_rate,
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
# MAGIC the 4A/4C and 4C/4D boundaries point straight at the descriptions that leak.

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
# MAGIC 1. Edit **one** surface in Section 1.
# MAGIC 2. Set a new `run_label` (e.g. `v2_tighten_4B_vs_4A`).
# MAGIC 3. Re-run from Section 0. Only the new config re-scores; everything else is instant.
# MAGIC 4. Compare runs in the Experiments UI (or Section 11 below).

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
        raw_codes = row.get("pred_codes_cache") if row.get("pred_codes_cache") is not None else (row.get("pred_codes") if row.get("pred_codes") is not None else [])
        raw_confs = row.get("pred_confidences_cache") if row.get("pred_confidences_cache") is not None else (row.get("pred_confidences") if row.get("pred_confidences") is not None else [])
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
# MAGIC
# MAGIC **Tip:** filter by `params.source` and `params.gepa_phase` to separate manual
# MAGIC baseline runs from GEPA-optimized runs at each phase.

# COMMAND ----------

_all_runs = mlflow.search_runs(order_by=["start_time DESC"])
if len(_all_runs) > 0:
    _metric_cols = [c for c in _all_runs.columns if c.startswith("metrics.")]
    _param_cols = [
        "params.run_label", "params.config_hash", "params.confidence_threshold",
        "params.prompt_registry_version", "params.n_eval_rows",
        "params.source", "params.gepa_phase",
        "params.descriptions_prompt_version", "params.instructions_prompt_version",
    ]
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
# MAGIC evolve your prompt text. It is powerful but carries risk:
# MAGIC
# MAGIC * It uses a **3-way split** (Section 3): train for optimization, validation for
# MAGIC   selecting the best candidate, and test for the final honest check.
# MAGIC * It can optimize **descriptions**, **instructions**, or **both jointly** — gated
# MAGIC   by the `gepa_phase` widget.
# MAGIC * Each GEPA iteration calls `ai_classify` per-row via SQL — this is **slow and
# MAGIC   costly** (train_size × max_metric_calls × per_call_cost). Budget accordingly.
# MAGIC
# MAGIC ### Phase strategy (recommended order)
# MAGIC
# MAGIC | Phase | What moves | When to use |
# MAGIC |-------|-----------|-------------|
# MAGIC | `descriptions` | Label descriptions only | Substitution errors dominate (bucket C); instructions are already solid |
# MAGIC | `instructions` | Instructions only | Over/under-assignment errors dominate (buckets A/B/E) |
# MAGIC | `joint` | Both surfaces together | After single-surface phases plateau; looking for synergies |
# MAGIC
# MAGIC > Set the `run_gepa` widget to `true` and `gepa_phase` to your choice to enable.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Section 12a — Shared GEPA infrastructure
# MAGIC
# MAGIC These utilities are used by all three GEPA phases: the predict function, the
# MAGIC scorer, the structural validator for descriptions, and the data preparation.

# COMMAND ----------

if RUN_GEPA:
    from mlflow.genai.optimize import GepaPromptOptimizer

    # ---- Structural validator for description candidates --------------------------------
    def validate_descriptions_json(candidate_text):
        """Validate that a GEPA-generated description candidate is valid JSON with exactly
        the right 6 keys and each value ≤ 1,000 characters.
        Returns (is_valid, error_message)."""
        try:
            parsed = json.loads(candidate_text)
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON: {e}"
        if not isinstance(parsed, dict):
            return False, f"Expected dict, got {type(parsed).__name__}"
        expected_keys = set(LABELS.keys())
        actual_keys = set(parsed.keys())
        if actual_keys != expected_keys:
            missing = expected_keys - actual_keys
            extra = actual_keys - expected_keys
            return False, f"Key mismatch. Missing: {missing}. Extra: {extra}."
        for k, v in parsed.items():
            if not isinstance(v, str):
                return False, f"Value for '{k}' is {type(v).__name__}, expected str."
            if len(v) > 1000:
                return False, f"Value for '{k[:10]}…' is {len(v)} chars (max 1000)."
        return True, "ok"

    # ---- Build GEPA data splits --------------------------------------------------------
    def _build_gepa_data(split_df):
        return [
            {
                "inputs": {"opportunity_id": r.opportunity_id, "transcript_text": r.transcript_text},
                "expectations": {"expected_codes": list(r.expected_codes)},
            }
            for _, r in split_df.iterrows()
        ]

    train_data_gepa = _build_gepa_data(train_pd)
    validation_data_gepa = _build_gepa_data(validation_pd)
    test_data_gepa = _build_gepa_data(test_pd)

    # ---- GEPA scorer: corpus micro-F1 with boundary confusion penalty ------------------
    # This scorer runs per-row but is designed so that when GEPA averages it across the
    # train set, the result approximates corpus micro-F1 with a penalty for boundary swaps.
    @scorer
    def gepa_micro_f1(outputs, expectations) -> Feedback:
        pred = _as_set(outputs)
        gold = _as_set(expectations.get("expected_codes"))
        tp = len(pred & gold)
        fp = len(pred - gold)
        fn = len(gold - pred)
        _, _, f1 = prf(tp, fp, fn)
        # Boundary penalty: subtract 0.1 for each boundary swap in this row
        missed = gold - pred
        added = pred - gold
        n_boundary_errors = sum(
            1 for a, b in _BOUNDARY_PAIRS
            if (a in missed and b in added) or (b in missed and a in added)
        )
        penalized_f1 = max(0.0, f1 - 0.1 * n_boundary_errors)
        rationale = f"row f1={f1:.2f}"
        if n_boundary_errors:
            rationale += f" (boundary penalty: -{0.1*n_boundary_errors:.1f})"
        return Feedback(value=penalized_f1, rationale=rationale)

    print(f"GEPA ready: {len(train_data_gepa)} train, {len(validation_data_gepa)} validation, "
          f"{len(test_data_gepa)} test rows.")
    print(f"Phase: {GEPA_PHASE}")
else:
    print("GEPA is OFF (set `run_gepa` widget to 'true' to enable).")

# COMMAND ----------

# MAGIC %md
# MAGIC ### GEPA predict function
# MAGIC
# MAGIC This function is called by GEPA for each row during optimization. It loads the
# MAGIC current prompt version(s) from the registry, builds the `ai_classify` SQL, and
# MAGIC runs it for a single row. Each call uses a **unique temp view** to avoid
# MAGIC concurrency hazards when GEPA runs multiple candidates.

# COMMAND ----------

if RUN_GEPA:
    def _make_gepa_predict_fn(desc_prompt_obj, instr_prompt_obj, phase):
        """Factory for GEPA predict functions that read the correct prompt(s)
        from the registry based on which phase is running."""

        def gepa_predict_fn(opportunity_id, transcript_text):
            # Load the current (GEPA-swapped) prompt version(s)
            if phase in ("descriptions", "joint"):
                desc_prompt = mlflow.genai.load_prompt(desc_prompt_obj.uri)
                desc_text = desc_prompt.template
                valid, err_msg = validate_descriptions_json(desc_text)
                if valid:
                    current_labels = json.loads(desc_text)
                else:
                    # If GEPA generated invalid JSON, fall back to baseline
                    current_labels = dict(LABELS)
            else:
                current_labels = dict(LABELS)

            if phase in ("instructions", "joint"):
                instr_prompt = mlflow.genai.load_prompt(instr_prompt_obj.uri)
                current_instructions = instr_prompt.template
            else:
                current_instructions = INSTRUCTIONS

            config = {"labels": current_labels, "instructions": current_instructions, "options": AI_OPTIONS}
            expr = build_ai_classify_expr("transcript_text", config)

            # Unique temp view name per call to avoid concurrency hazards
            view_id = uuid.uuid4().hex[:8]
            view_name = f"_gepa_row_{view_id}"

            row_df = spark.createDataFrame([(transcript_text,)], ["transcript_text"])
            row_df.createOrReplaceTempView(view_name)

            result = spark.sql(f"""
                SELECT transform(
                    ({expr}):response::ARRAY<STRUCT<value:STRING,confidence_score:DOUBLE,rationale:STRING>>,
                    x -> x.value
                ) AS pred_codes FROM {view_name}
            """).collect()[0]

            codes = [c[:2] for c in (result.pred_codes or [])]
            return {"codes": codes}

        return gepa_predict_fn

    print("✓ GEPA predict function factory ready.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### GEPA evaluation on the untouched test split
# MAGIC
# MAGIC After GEPA finishes, we always evaluate on the **test split** for an honest,
# MAGIC independent assessment. This function is shared across all phases.

# COMMAND ----------

if RUN_GEPA:
    def _evaluate_gepa_result(gepa_result, phase_label, optimized_config, optimized_hash):
        """Cache predictions for the optimized config, then run evaluate() on the test split."""
        # Cache predictions for the full dataset (for completeness)
        classify_and_cache(optimized_config, optimized_hash)

        # Load cached predictions
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
            pairs = _GEPA_PREDS.get(opportunity_id, [])
            codes = [c[:2] for (c, conf) in pairs if (conf is None or conf >= CONFIDENCE_THRESHOLD)]
            confidences = [conf for (c, conf) in pairs if (conf is None or conf >= CONFIDENCE_THRESHOLD)]
            rationales = _GEPA_RATS.get(opportunity_id, [])
            return {"codes": codes, "confidences": confidences, "rationales": rationales}

        with mlflow.start_run(run_name=f"{RUN_LABEL}_gepa_{phase_label}_test") as gepa_test_run:
            mlflow.log_params({
                "config_hash": optimized_hash,
                "confidence_threshold": CONFIDENCE_THRESHOLD,
                "n_eval_rows": len(test_data_gepa),
                "split": "test (untouched by GEPA)",
                "source": f"GEPA-{phase_label}",
                "gepa_phase": phase_label,
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
        print(f"  GEPA {phase_label.upper()} — HONEST TEST-SPLIT EVALUATION")
        print(f"  (this split was NEVER seen during optimization)")
        print(f"{'='*60}")
        print(f"  GEPA train score      : {gepa_result.initial_eval_score:.3f} → {gepa_result.final_eval_score:.3f}")
        print(f"  Test-split metrics    :")
        for k, v in sorted((gepa_test_result.metrics or {}).items()):
            print(f"    {k}: {v}")
        print(f"\n  ⚠ Compare the test-split numbers against the baseline's FULL-dataset")
        print(f"    numbers with caution — different denominators. The key question is:")
        print(f"    did GEPA find a GENERALIZABLE improvement, or did it overfit?")
        print(f"\n✓ GEPA-{phase_label} optimized config cached (hash={optimized_hash}).")
        return gepa_test_result

    print("✓ GEPA evaluation helper ready.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Section 12b — Phase: descriptions
# MAGIC
# MAGIC Optimize the 6 label descriptions while holding instructions fixed. Best when
# MAGIC substitution errors (bucket C) dominate — the descriptions control the *boundaries*
# MAGIC between codes.
# MAGIC
# MAGIC The structural validator ensures GEPA only considers candidates that are valid JSON
# MAGIC with exactly 6 keys and ≤1,000 chars per value.

# COMMAND ----------

if RUN_GEPA and GEPA_PHASE in ("descriptions", "joint"):
    print(f"=== GEPA PHASE: descriptions ===")

    # Register (or reuse) the descriptions prompt for GEPA to evolve
    try:
        _desc_for_gepa = _register_if_changed(
            name=DESCRIPTIONS_PROMPT_NAME,
            template=json.dumps(LABELS, ensure_ascii=False, indent=2),
            commit_message=f"Baseline descriptions for GEPA ({RUN_LABEL})",
        )
    except Exception as e:
        print(f"⚠ Cannot register descriptions prompt: {e}")
        _desc_for_gepa = None

    if _desc_for_gepa:
        _instr_for_desc_gepa = INSTR_PROMPT_VERSION  # instructions stay fixed
        if _instr_for_desc_gepa is None:
            # If instructions prompt isn't registered, register it now
            try:
                _instr_for_desc_gepa = _register_if_changed(
                    name=INSTRUCTIONS_PROMPT_NAME,
                    template=INSTRUCTIONS,
                    commit_message=f"Baseline instructions (held fixed for desc GEPA)",
                )
            except Exception:
                pass

        if _instr_for_desc_gepa:
            predict_fn_desc = _make_gepa_predict_fn(_desc_for_gepa, _instr_for_desc_gepa, "descriptions")

            print(f"Starting GEPA descriptions optimization — this may take a while...")
            print(f"  Train rows: {len(train_data_gepa)}")
            print(f"  Prompt URI: {_desc_for_gepa.uri if hasattr(_desc_for_gepa, 'uri') else 'N/A'}")

            try:
                gepa_desc_result = mlflow.genai.optimize_prompts(
                    predict_fn=predict_fn_desc,
                    train_data=train_data_gepa,
                    prompt_uris=[_desc_for_gepa.uri],
                    optimizer=GepaPromptOptimizer(
                        reflection_model="databricks:/databricks-claude-sonnet-5",
                        max_metric_calls=50,
                        display_progress_bar=True,
                    ),
                    scorers=[gepa_micro_f1],
                )

                optimized_desc_text = gepa_desc_result.optimized_prompts[0].template
                valid, err_msg = validate_descriptions_json(optimized_desc_text)
                if valid:
                    optimized_labels = json.loads(optimized_desc_text)
                    print(f"\n✓ GEPA descriptions optimization complete.")
                    print(f"  Initial score: {gepa_desc_result.initial_eval_score:.3f}")
                    print(f"  Final score:   {gepa_desc_result.final_eval_score:.3f}")

                    # Register the optimized descriptions
                    mlflow.genai.register_prompt(
                        name=DESCRIPTIONS_PROMPT_NAME,
                        template=optimized_desc_text,
                        commit_message=f"GEPA-desc ({gepa_desc_result.initial_eval_score:.3f} → {gepa_desc_result.final_eval_score:.3f})",
                    )

                    # Evaluate on test split
                    opt_desc_config = {"labels": optimized_labels, "instructions": INSTRUCTIONS, "options": AI_OPTIONS}
                    opt_desc_hash = hashlib.sha256(
                        json.dumps(opt_desc_config, sort_keys=True).encode()
                    ).hexdigest()[:16]
                    _evaluate_gepa_result(gepa_desc_result, "descriptions", opt_desc_config, opt_desc_hash)
                else:
                    print(f"⚠ GEPA produced invalid descriptions: {err_msg}")
                    print(f"  Raw output (first 500 chars): {optimized_desc_text[:500]}")

            except Exception as e:
                print(f"⚠ GEPA descriptions failed: {type(e).__name__}: {e}")
        else:
            print("⚠ Skipping descriptions GEPA — cannot register instructions prompt.")
    else:
        print("⚠ Skipping descriptions GEPA — cannot register descriptions prompt.")
elif RUN_GEPA:
    print(f"Skipping descriptions phase (current phase: {GEPA_PHASE}).")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Section 12c — Phase: instructions
# MAGIC
# MAGIC Optimize the global instructions while holding descriptions fixed. Best when
# MAGIC over-assignment (bucket A) or under-assignment (bucket B/E) errors dominate —
# MAGIC the instructions control *when to assign anything at all*.

# COMMAND ----------

if RUN_GEPA and GEPA_PHASE in ("instructions", "joint"):
    print(f"=== GEPA PHASE: instructions ===")

    # Register (or reuse) the instructions prompt for GEPA to evolve
    try:
        _instr_for_gepa = _register_if_changed(
            name=INSTRUCTIONS_PROMPT_NAME,
            template=INSTRUCTIONS,
            commit_message=f"Baseline instructions for GEPA ({RUN_LABEL})",
        )
    except Exception as e:
        print(f"⚠ Cannot register instructions prompt: {e}")
        _instr_for_gepa = None

    if _instr_for_gepa:
        _desc_for_instr_gepa = DESC_PROMPT_VERSION  # descriptions stay fixed
        if _desc_for_instr_gepa is None:
            try:
                _desc_for_instr_gepa = _register_if_changed(
                    name=DESCRIPTIONS_PROMPT_NAME,
                    template=json.dumps(LABELS, ensure_ascii=False, indent=2),
                    commit_message=f"Baseline descriptions (held fixed for instr GEPA)",
                )
            except Exception:
                pass

        if _desc_for_instr_gepa:
            predict_fn_instr = _make_gepa_predict_fn(_desc_for_instr_gepa, _instr_for_gepa, "instructions")

            print(f"Starting GEPA instructions optimization — this may take a while...")
            print(f"  Train rows: {len(train_data_gepa)}")
            print(f"  Prompt URI: {_instr_for_gepa.uri if hasattr(_instr_for_gepa, 'uri') else 'N/A'}")

            try:
                gepa_instr_result = mlflow.genai.optimize_prompts(
                    predict_fn=predict_fn_instr,
                    train_data=train_data_gepa,
                    prompt_uris=[_instr_for_gepa.uri],
                    optimizer=GepaPromptOptimizer(
                        reflection_model="databricks:/databricks-claude-sonnet-5",
                        max_metric_calls=50,
                        display_progress_bar=True,
                    ),
                    scorers=[gepa_micro_f1],
                )

                optimized_instr_text = gepa_instr_result.optimized_prompts[0].template
                print(f"\n✓ GEPA instructions optimization complete.")
                print(f"  Initial score: {gepa_instr_result.initial_eval_score:.3f}")
                print(f"  Final score:   {gepa_instr_result.final_eval_score:.3f}")
                print(f"  Optimized instructions (first 500 chars):\n{optimized_instr_text[:500]}...")

                # Register the optimized instructions
                mlflow.genai.register_prompt(
                    name=INSTRUCTIONS_PROMPT_NAME,
                    template=optimized_instr_text,
                    commit_message=f"GEPA-instr ({gepa_instr_result.initial_eval_score:.3f} → {gepa_instr_result.final_eval_score:.3f})",
                )

                # Evaluate on test split
                opt_instr_config = {"labels": LABELS, "instructions": optimized_instr_text, "options": AI_OPTIONS}
                opt_instr_hash = hashlib.sha256(
                    json.dumps(opt_instr_config, sort_keys=True).encode()
                ).hexdigest()[:16]
                _evaluate_gepa_result(gepa_instr_result, "instructions", opt_instr_config, opt_instr_hash)

            except Exception as e:
                print(f"⚠ GEPA instructions failed: {type(e).__name__}: {e}")
        else:
            print("⚠ Skipping instructions GEPA — cannot register descriptions prompt.")
    else:
        print("⚠ Skipping instructions GEPA — cannot register instructions prompt.")
elif RUN_GEPA:
    print(f"Skipping instructions phase (current phase: {GEPA_PHASE}).")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Section 12d — Phase: joint
# MAGIC
# MAGIC Optimize **both** descriptions and instructions simultaneously. This is the most
# MAGIC expensive mode and should only be used after single-surface phases have plateaued.
# MAGIC GEPA evolves both prompt URIs together, looking for synergies.
# MAGIC
# MAGIC > **Warning:** joint optimization searches a much larger space. It will take
# MAGIC > significantly more iterations and LLM calls than single-surface phases.

# COMMAND ----------

if RUN_GEPA and GEPA_PHASE == "joint":
    print(f"=== GEPA PHASE: joint (descriptions + instructions) ===")

    # Ensure both prompts are registered
    try:
        _desc_for_joint = _register_if_changed(
            name=DESCRIPTIONS_PROMPT_NAME,
            template=json.dumps(LABELS, ensure_ascii=False, indent=2),
            commit_message=f"Baseline descriptions for joint GEPA ({RUN_LABEL})",
        )
        _instr_for_joint = _register_if_changed(
            name=INSTRUCTIONS_PROMPT_NAME,
            template=INSTRUCTIONS,
            commit_message=f"Baseline instructions for joint GEPA ({RUN_LABEL})",
        )
    except Exception as e:
        print(f"⚠ Cannot register prompts: {e}")
        _desc_for_joint = None
        _instr_for_joint = None

    if _desc_for_joint and _instr_for_joint:
        predict_fn_joint = _make_gepa_predict_fn(_desc_for_joint, _instr_for_joint, "joint")

        print(f"Starting GEPA joint optimization — this will be expensive...")
        print(f"  Train rows: {len(train_data_gepa)}")
        print(f"  Optimizing 2 prompts simultaneously")

        try:
            gepa_joint_result = mlflow.genai.optimize_prompts(
                predict_fn=predict_fn_joint,
                train_data=train_data_gepa,
                prompt_uris=[_desc_for_joint.uri, _instr_for_joint.uri],
                optimizer=GepaPromptOptimizer(
                    reflection_model="databricks:/databricks-claude-sonnet-5",
                    max_metric_calls=80,  # more budget for joint search
                    display_progress_bar=True,
                ),
                scorers=[gepa_micro_f1],
            )

            # Unpack both optimized prompts
            opt_desc_text_joint = gepa_joint_result.optimized_prompts[0].template
            opt_instr_text_joint = gepa_joint_result.optimized_prompts[1].template

            # Validate descriptions
            valid, err_msg = validate_descriptions_json(opt_desc_text_joint)
            if valid:
                opt_labels_joint = json.loads(opt_desc_text_joint)
            else:
                print(f"⚠ Joint GEPA produced invalid descriptions: {err_msg}")
                opt_labels_joint = dict(LABELS)  # fall back

            print(f"\n✓ GEPA joint optimization complete.")
            print(f"  Initial score: {gepa_joint_result.initial_eval_score:.3f}")
            print(f"  Final score:   {gepa_joint_result.final_eval_score:.3f}")

            # Register optimized versions
            mlflow.genai.register_prompt(
                name=DESCRIPTIONS_PROMPT_NAME,
                template=opt_desc_text_joint,
                commit_message=f"GEPA-joint desc ({gepa_joint_result.initial_eval_score:.3f} → {gepa_joint_result.final_eval_score:.3f})",
            )
            mlflow.genai.register_prompt(
                name=INSTRUCTIONS_PROMPT_NAME,
                template=opt_instr_text_joint,
                commit_message=f"GEPA-joint instr ({gepa_joint_result.initial_eval_score:.3f} → {gepa_joint_result.final_eval_score:.3f})",
            )

            # Evaluate on test split
            opt_joint_config = {"labels": opt_labels_joint, "instructions": opt_instr_text_joint, "options": AI_OPTIONS}
            opt_joint_hash = hashlib.sha256(
                json.dumps(opt_joint_config, sort_keys=True).encode()
            ).hexdigest()[:16]
            _evaluate_gepa_result(gepa_joint_result, "joint", opt_joint_config, opt_joint_hash)

        except Exception as e:
            print(f"⚠ GEPA joint optimization failed: {type(e).__name__}: {e}")
    else:
        print("⚠ Skipping joint GEPA — cannot register one or both prompts.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 13 — Promote the winning prompt
# MAGIC
# MAGIC Once a variant is a defensible improvement, **promote it** by setting the
# MAGIC `"production"` alias on its Prompt Registry version. We promote all three
# MAGIC registered prompts (descriptions, instructions, and the full bundle) so the
# MAGIC production pipeline can read from whichever level of granularity it needs:
# MAGIC
# MAGIC ```python
# MAGIC # In the production pipeline (future state):
# MAGIC prompt = mlflow.genai.load_prompt(f"prompts:/{BUNDLE_PROMPT_NAME}@production")
# MAGIC config = json.loads(prompt.template)
# MAGIC # ... build ai_classify SQL from config ...
# MAGIC ```
# MAGIC
# MAGIC **For now**, you copy the winning `LABELS` + `INSTRUCTIONS` back into
# MAGIC `gold_opportunity_enrichment.sql`. The registry alias is the path to automating
# MAGIC that handoff.

# COMMAND ----------

# Promote the bundle prompt
if BUNDLE_PROMPT_VERSION:
    try:
        mlflow.genai.set_prompt_alias(
            name=BUNDLE_PROMPT_NAME,
            alias="production",
            version=BUNDLE_PROMPT_VERSION.version,
        )
        print(f"✓ Promoted bundle '{BUNDLE_PROMPT_NAME}' v{BUNDLE_PROMPT_VERSION.version} to @production.")
    except Exception as e:
        print(f"(Could not set bundle alias: {type(e).__name__}: {e})")

# Promote the descriptions prompt
if DESC_PROMPT_VERSION:
    try:
        mlflow.genai.set_prompt_alias(
            name=DESCRIPTIONS_PROMPT_NAME,
            alias="production",
            version=DESC_PROMPT_VERSION.version,
        )
        print(f"✓ Promoted descriptions '{DESCRIPTIONS_PROMPT_NAME}' v{DESC_PROMPT_VERSION.version} to @production.")
    except Exception as e:
        print(f"(Could not set descriptions alias: {type(e).__name__}: {e})")

# Promote the instructions prompt
if INSTR_PROMPT_VERSION:
    try:
        mlflow.genai.set_prompt_alias(
            name=INSTRUCTIONS_PROMPT_NAME,
            alias="production",
            version=INSTR_PROMPT_VERSION.version,
        )
        print(f"✓ Promoted instructions '{INSTRUCTIONS_PROMPT_NAME}' v{INSTR_PROMPT_VERSION.version} to @production.")
    except Exception as e:
        print(f"(Could not set instructions alias: {type(e).__name__}: {e})")

if not any([BUNDLE_PROMPT_VERSION, DESC_PROMPT_VERSION, INSTR_PROMPT_VERSION]):
    print("No Prompt Registry versions to promote. The full config is logged as "
          "prompt_config.json on the MLflow run — copy LABELS + INSTRUCTIONS to the pipeline SQL.")

print(f"\nLoad production prompts anywhere with:")
print(f"  mlflow.genai.load_prompt('prompts:/{BUNDLE_PROMPT_NAME}@production')")
print(f"  mlflow.genai.load_prompt('prompts:/{DESCRIPTIONS_PROMPT_NAME}@production')")
print(f"  mlflow.genai.load_prompt('prompts:/{INSTRUCTIONS_PROMPT_NAME}@production')")

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
# MAGIC ### 2. GEPA phase sequencing
# MAGIC
# MAGIC Run GEPA phases in this order for best results:
# MAGIC
# MAGIC 1. **`instructions` first** — fixes over/under-assignment (the biggest lever).
# MAGIC    After it converges, promote the winning instructions and set them as the new
# MAGIC    baseline in Section 1.
# MAGIC 2. **`descriptions` second** — fixes boundary/substitution errors between adjacent
# MAGIC    codes. With better instructions as the baseline, description optimization is
# MAGIC    more focused.
# MAGIC 3. **`joint` last** — only if single-surface phases have plateaued. The joint
# MAGIC    search space is much larger, so it needs more iterations and more data.
# MAGIC
# MAGIC Between phases, **update the baseline**: copy the GEPA-optimized text back into
# MAGIC the Section 1 cells, set a new `run_label`, and re-evaluate on the full dataset
# MAGIC to confirm the improvement before proceeding.
# MAGIC
# MAGIC ### 3. Integrate the Prompt Registry with the pipeline
# MAGIC Today, the pipeline hardcodes labels + instructions in SQL. The future state:
# MAGIC ```python
# MAGIC # In the pipeline's Python wrapper:
# MAGIC prompt = mlflow.genai.load_prompt(f"prompts:/{BUNDLE_PROMPT_NAME}@production")
# MAGIC config = json.loads(prompt.template)
# MAGIC # Build the ai_classify SQL from `config` and inject it into the MV definition.
# MAGIC ```
# MAGIC This closes the loop: **tune here → promote → pipeline picks it up automatically**.
# MAGIC
# MAGIC ### 4. Measure model stochasticity
# MAGIC `ai_classify` is non-deterministic. To show the *second* noise floor, re-run one
# MAGIC config 3–5× with the cache cleared for that hash (delete from `ai_classify_eval_cache
# MAGIC WHERE config_hash = '...'`), and watch micro-F1 wobble with the prompt held fixed.
# MAGIC
# MAGIC ### 5. Production monitoring
# MAGIC Once the pipeline is reading from the registry, register an MLflow scorer against
# MAGIC the experiment and start production monitoring:
# MAGIC ```python
# MAGIC from mlflow.genai.scorers import ScorerSamplingConfig
# MAGIC quality_scorer = my_scorer.register(name="offer_blocker_quality")
# MAGIC quality_scorer.start(sampling_config=ScorerSamplingConfig(sample_rate=0.1))
# MAGIC ```
# MAGIC
# MAGIC ### 6. The qualifier layer
# MAGIC `gold_findings_raw` runs a finer-grained qualifier classification per code
# MAGIC (e.g. 4A → `current-supplier` / `competitor-rate` / …). The **same eval harness**
# MAGIC generalizes: swap the labels dict, build a parallel eval table, and re-use this
# MAGIC notebook's Sections 4–11 unchanged.
