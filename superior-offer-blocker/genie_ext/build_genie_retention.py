#!/usr/bin/env python3
"""Build genie_retention.json (serialized_space v2) for the Customer Retention
Decision Agent. Skill-compliant: metric-view source, MEASURE() example SQL,
5-header text instructions, benchmarks; all id-keyed arrays sorted by id.

Deterministic IDs (no random) so re-runs produce a stable, diff-able file.
Usage:  python3 build_genie_retention.py > genie_retention.json
"""
import json

MV = "${catalog}.${schema}.mv_retention"  # remapped at deploy time by genie_setup

def sid(n: int) -> str:      # sample-question ids: 32-hex
    return f"5{n:031x}"
def eid(n: int) -> str:      # example-sql ids
    return f"e{n:031x}"
def tid(n: int) -> str:      # text-instruction id
    return f"a{n:031x}"
def bid(n: int) -> str:      # benchmark ids
    return f"b{n:031x}"

sample_questions = [
    "How many opportunities are in the High churn-risk tier by region?",
    "Which NY and NJ opportunities have a rate objection and a verified runout or late delivery? Rank by contribution.",
    "Split my NY and NJ book into Can Raise vs Protect and show contribution at risk.",
    "What is the average rate gap versus competitors for Protect-segment accounts?",
    "What is the net annual contribution at 0.5, 1, and 2 points of churn reduction?",
]

# (question, sql) — every column qualified to the metric view's last segment; MEASURE() for measures.
example_sqls = [
    ("How many at-risk opportunities are there by region?",
     "SELECT mv_retention.`Region`, MEASURE(mv_retention.`At-Risk Opportunities`) AS at_risk "
     "FROM " + MV + " GROUP BY mv_retention.`Region` ORDER BY at_risk DESC"),
    ("Which opportunities are the rate-objection-plus-service-failure cohort in NY and NJ, ranked by contribution?",
     "SELECT mv_retention.`Region`, MEASURE(mv_retention.`Rate Objection And Failure`) AS aha_cohort, "
     "MEASURE(mv_retention.`Contribution At Risk`) AS contribution_at_risk "
     "FROM " + MV + " WHERE mv_retention.`Region` IN ('New York','New Jersey') "
     "GROUP BY mv_retention.`Region` ORDER BY contribution_at_risk DESC"),
    ("Show the raise-versus-protect split and contribution at risk for NY and NJ.",
     "SELECT mv_retention.`Segment`, MEASURE(mv_retention.`Opportunities`) AS opportunities, "
     "MEASURE(mv_retention.`Contribution At Risk`) AS contribution_at_risk "
     "FROM " + MV + " WHERE mv_retention.`Region` IN ('New York','New Jersey') "
     "GROUP BY mv_retention.`Segment`"),
    ("What is the average rate gap versus competitors for Protect accounts?",
     "SELECT MEASURE(mv_retention.`Avg Rate Gap`) AS avg_rate_gap "
     "FROM " + MV + " WHERE mv_retention.`Segment` = 'Protect'"),
    ("What is the illustrative net contribution per point of churn reduction?",
     "SELECT MEASURE(mv_retention.`Net Contribution Per Churn Point`) AS net_per_point FROM " + MV),
]

# Benchmarks: mix of single_sql_answer (deterministic) and multi_step_agent_analysis (empty content + evaluation_note)
benchmarks = [
    ("single", "How many High churn-risk opportunities are there in New York?",
     "SELECT MEASURE(mv_retention.`At-Risk Opportunities`) AS at_risk FROM " + MV +
     " WHERE mv_retention.`Region` = 'New York' AND mv_retention.`Churn Risk Tier` = 'High'", None),
    ("single", "What is the total contribution at risk in the Protect segment for NY and NJ?",
     "SELECT MEASURE(mv_retention.`Contribution At Risk`) AS car FROM " + MV +
     " WHERE mv_retention.`Region` IN ('New York','New Jersey')", None),
    ("agent", "Which accounts should we protect rather than raise price on, and why?", None,
     "Agent must use the Segment dimension (Protect) AND cite supporting evidence from at least two of: "
     "churn-risk tier, rate objection + verified failure cohort, and contribution at risk. Reject if it "
     "recommends a blanket price action or omits the service-failure rationale."),
    ("agent", "If we reduce avoidable churn by 2 points, what is the net contribution and how confident should we be?",
     None,
     "Agent must multiply Net Contribution Per Churn Point by 2 (=> ~$1,050,000), explicitly label it illustrative "
     "(not booked EBITDA), and state the $600/acct + $150k-cost + 100k-base assumptions. Reject if presented as actual results."),
]

# --- text instructions: five canonical headers, < 2000 chars, one item ---
text_instruction = [
    "## PURPOSE",
    "- Answer retention-aware pricing questions for Superior Plus Propane on the NY/NJ book.",
    "- Users are VP Sales/Ops and Finance; assume commercial fluency.",
    "",
    "## DISAMBIGUATION",
    "- 'At risk' means Churn Risk Tier = 'High' unless the user specifies another tier.",
    "- 'Protect' vs 'Can Raise' refers to the Segment dimension, not deal stage.",
    "",
    "## DATA QUALITY NOTES",
    "- Delivery, fee, and contribution values are synthetic (is_synthetic = true); CX and blocker signals derive from real call data.",
    "- A runout counts only when verified by a delivery record; do not infer failures from complaints alone.",
    "",
    "## CONSTRAINTS",
    "- Churn-risk tiers are rule-based; never present them as calibrated probabilities.",
    "- Scope answers to New York and New Jersey unless the user names another region.",
    "",
    "## Instructions you must follow when providing summaries",
    "- Always label the churn-reduction economics as illustrative, not booked EBITDA.",
    "- State the assumptions ($600/account, $150k program cost, 100k-account base) whenever you report a dollar scenario.",
]

def build():
    payload = {
        "version": 2,
        "config": {
            "sample_questions": sorted(
                [{"id": sid(i), "question": [q]} for i, q in enumerate(sample_questions, 1)],
                key=lambda x: x["id"]),
        },
        "data_sources": {
            "metric_views": [{
                "identifier": MV,
                "column_configs": sorted([
                    {"column_name": "Region", "enable_format_assistance": True, "enable_entity_matching": True,
                     "synonyms": ["state", "market"]},
                    {"column_name": "Segment", "enable_entity_matching": True,
                     "description": ["Strategic pricing call: Protect = do not raise; Can Raise = resilient."]},
                    {"column_name": "Churn Risk Tier", "enable_entity_matching": True},
                ], key=lambda c: c["column_name"]),
            }],
        },
        "instructions": {
            "example_question_sqls": sorted(
                [{"id": eid(i), "question": [q], "sql": [s]} for i, (q, s) in enumerate(example_sqls, 1)],
                key=lambda x: x["id"]),
            "text_instructions": [{"id": tid(1), "content": text_instruction}],
        },
        "benchmarks": {
            "questions": sorted([
                ({"id": bid(i), "question": [q],
                  "answer": [{"format": "SQL", "content": [sql] if sql else []}]}
                 | ({"evaluation_note": [note]} if note else {}))
                for i, (kind, q, sql, note) in enumerate(benchmarks, 1)
            ], key=lambda x: x["id"]),
        },
    }
    return json.dumps(payload, indent=2)

if __name__ == "__main__":
    print(build())
