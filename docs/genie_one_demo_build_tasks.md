# Genie One Demo — Build Task List
**Customer:** Superior Plus Propane · **Anchor outcome:** Retention-aware pricing — capture pricing upside without buying it back in attrition · **Pillar:** Superior Delivers → Customer Growth (~$30M) · **Orchestration:** **Native Genie One only** (no Supervisor Agent / Agent Bricks)

> **Native-only design principle.** Native Genie One routes each question to the single best-fit Genie space and can search other assets, but does **not** guarantee a live 4-way join across spaces. Therefore all cross-domain synthesis is **pre-materialized in the pipeline** into one account-grain table (`account_retention_snapshot`) exposed through the **Customer Retention Decision** space. Strategic questions route there (join already done); the other three spaces serve single-domain drill-down and evidence. Never script a demo question that depends on Genie live-joining two separate spaces.

Region scope for the live demo: **New York + New Jersey, USD, gallons.** MA/CT/Ontario reserved for the "expansion" talking point.

---

## Phase 0 — Capability check & semantic spine (Day 1) — *blocking*
- [ ] **T0.1 Workspace capability check.** In the customer/demo workspace confirm: Genie enabled; the four spaces can be created and shared to the demo user; UC catalog/schema access; SQL warehouse (`50ad3a9993503e5b` or demo equivalent) is running. Native Genie One only — do **not** enable/rely on Supervisor Agent.
- [ ] **T0.2 Define the account spine.** Standardize `account_id`, `service_location_id`, `region`, and `as_of_date` as the join keys across every new table. Document in `docs/semantic_spine.md`.
- [ ] **T0.3 Certify non-overlapping metric names per space** (prevents native-router ambiguity): Voice owns `blocker_code`, `unresolved_issue_flag`; CX owns `avg_hold_seconds`, `abandon_rate`, `repeat_contact_flag`, `csat_index`; Delivery owns `runout_verified_flag`, `late_delivery_rate`, `days_to_empty`; Economics owns `trailing_contribution`, `rate_gap_vs_competitor`, `intervention_eligibility`, `churn_risk_tier`.
- [ ] **T0.4 Freeze the demo economics model** (illustrative, labeled): 100K-account population · 2pt churn reduction · $600 contribution/retained account · $150K program cost → $1.05M net; break-even 0.25pt / 250 accounts. Put constants in a seed so Genie can compute them live.

## Phase 1 — Foundation fix: preserve non-sales interactions (Days 2–3) — *blocking*
> The current silver layer inner-joins calls to Salesforce by phone and drops out-of-region rows, so existing-customer / service / unmatched calls vanish. Retention needs those calls.
- [ ] **T1.1 Add a bronze-branch customer-interaction path.** New MV `silver_customer_interaction` built **directly from `bronze_transcripts`**, *before* the opportunity join, preserving ops fields (queue/hold/abandon/talk seconds, `agentName`/`teamName`/`skillName`, `csatSentiment`+index, disposition, region) and **all** interactions including those with no opportunity. Ref today's dropper: `pipeline/transformations/silver/silver_transcript_sf_joined.sql:43` (`JOIN ... ON sf.contact_phone = t.phone10`) and `:27` (`valid_region ... DROP ROW`).
- [ ] **T1.2 Keep the sales branch intact.** Do **not** modify `silver_transcript_sf_joined` / `gold_offer_blockers*`; the existing Offer Blocker space and dashboard must keep working unchanged.
- [ ] **T1.3 Identity crosswalk.** Add `dim_account` + a phone→account crosswalk with a `match_confidence`; treat phone match as fallback, not authoritative. Classify each interaction: prospect / active customer / former customer / unmatched.
- [ ] **T1.4 Provenance columns.** Add `source_system`, `is_synthetic`, `data_as_of` to every new table so the demo can honestly label synthetic vs real.

## Phase 2 — Domain 2: Customer Experience / Contact-Center Ops (Day 4) — *real data*
- [ ] **T2.1 Build `gold_cx_contact` (contact grain) + `gold_cx_case`** from `silver_customer_interaction`: `avg_hold_seconds`, `abandon_rate`, `repeat_contact_flag`, `handle_seconds`, transfers, disposition, `csat_index`, agent/team/skill rollups.
- [ ] **T2.2 Create Genie space "CX & Service Recovery"** (new `genie/genie_cx.json`, provisioned by a parameterized copy of `src/setup/genie_setup.py`, title-idempotent). 6–8 benchmark questions. Guardrail note in instructions: *transcript-bearing calls are not the full offered-contact population — do not report enterprise abandonment rates.*

## Phase 3 — Domain 3: Delivery Reliability & Capacity (Days 5–6) — *synthetic, labeled*
- [ ] **T3.1 Generate `gold_delivery_order`** (promised vs actual time, gallons, status, `runout_verified_flag`, emergency flag) and `gold_route_day` (capacity, miles, stops, cost) keyed to the same accounts. Seed realistic correlations (some at-risk accounts have verified runouts). Telemetry (`tank_reading`) optional/out-of-MVP.
- [ ] **T3.2 Create Genie space "Delivery Reliability"** (`genie/genie_delivery.json`). Instructions must enforce: a reported runout becomes **verified** only with an operational delivery record; otherwise answer *unverified*.

## Phase 4 — Domain 4: Customer Economics & Retention + the decision table (Days 6–7) — *the native-synthesis core*
- [ ] **T4.1 Promote pricing signal.** Build `gold_pricing_position` from the existing `ai_extract` quoted-vs-competitor rates (`gold_opportunity_enrichment`) → `rate_gap_vs_competitor`; add synthetic `gold_billing_fees` + `gold_invoice_dispute` keyed by account.
- [ ] **T4.2 Build the load-bearing `account_retention_snapshot`** (one row per `account_id` × `as_of_date`). **Aggregate each source to account grain BEFORE joining** (avoid call×delivery×invoice fan-out inflating counts/dollars). Columns: unresolved commercial/service issue flags, repeat-contact & queue measures, verified delivery exceptions, effective price changes & disputed fees, trailing contribution, customer status, intervention eligibility, evidence coverage, and a transparent **`churn_risk_tier`** (rule-based — *no calibrated probabilities without a validated model*).
- [ ] **T4.3 Create Genie space "Customer Retention Decision"** (`genie/genie_retention.json`) over `account_retention_snapshot` + `intervention_policy` + the economics seed. **This is the space every strategic/CFO demo question routes to.** Add the raise-vs-protect segmentation logic and the $/churn-point math as certified SQL snippets.

## Phase 5 — Native Genie One wiring + golden-question eval (Days 8–9) — *demo-critical*
- [ ] **T5.1 Author space descriptions/instructions for clean native routing.** Each space's title + description must make the router's choice obvious from vocabulary (Voice=objections/blockers, CX=hold/abandon/CSAT, Delivery=runout/late/route, Retention=raise/protect/contribution/$). Overlap here is the #1 cause of mis-routing.
- [ ] **T5.2 Build the golden-question set** (~15–20, including all 7 demo questions). For each: expected space, expected shape, and a labeled fallback screenshot. Run repeatedly; pin exact wording that routes correctly.
- [ ] **T5.3 Confirm cross-domain questions resolve inside ONE space.** Every "cross-domain" demo question must be answerable from `account_retention_snapshot` alone (Retention space). If a question tries to force a live 2-space join, rewrite it or push the join into the snapshot. *This is the native-only guardrail.*
- [ ] **T5.4 Cross-domain-aware follow-up email.** Extend existing `gold_followup_email_enh` (`ai_query`/claude-opus) so the draft cites the specific service issue (runout/late) from the snapshot, not just the sales objection.

## Phase 6 — Dashboard, contrasting stories & rehearsal (Day 10)
- [ ] **T6.1 Add "Retention-Aware Pricing" dashboard page** (raise vs protect segments, EBITDA-at-stake, churn-risk tiers) alongside the existing Executive Overview / Call Intelligence pages; keep the Genie link.
- [ ] **T6.2 Seed 5 contrasting demo accounts:** (a) price complaint + verified delivery failure → service recovery first; (b) price complaint, no failure, healthy contribution → commercial review; (c) repeat billing-confusion contacts → clarify, don't discount; (d) confirmed move → not addressable churn; (e) missing dispatch evidence → answer *unverified*.
- [ ] **T6.3 Freeze demo snapshot, preload session, rehearse twice** with a labeled fallback for every live query. Practice the 20-min track end to end.

---
## Sequencing / de-risk
- Phases 0–2 use **real data** — if time runs short, you still have a genuine **two-space native Genie One** (Offer Blocker + CX Ops) that beats today's single space.
- Estimated **~10 working days** for a synthetic demo, assuming the existing bundle deploys and Genie is enabled.
- **Out of MVP:** live telemetry ingestion, route optimization, demand-model training, wholesale analytics, Salesforce/dispatch write-back, calibrated churn probabilities.
