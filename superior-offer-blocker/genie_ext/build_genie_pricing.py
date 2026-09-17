#!/usr/bin/env python3
"""Build genie_pricing.json — Pricing Position Agent (serialized_space v2).
Source: mv_pricing. Skill-compliant; ids 32-hex lowercase and id-sorted.
Usage: python3 build_genie_pricing.py > genie_pricing.json
"""
import json
MV = "${catalog}.${schema}.mv_pricing"
def sid(n): return f"5{n:031x}"
def eid(n): return f"e{n:031x}"
def tid(n): return f"a{n:031x}"
def bid(n): return f"b{n:031x}"

sample_questions = [
    "What is our average rate gap versus competitors?",
    "How does the average quoted rate compare to the competitor rate by stage?",
    "What is the average fee load by Salesforce stage?",
    "Which stage has the largest rate gap versus market?",
    "How many opportunities have a quoted rate above the competitor rate?",
]
example_sqls = [
    ("What is our average rate gap versus competitors?",
     "SELECT MEASURE(mv_pricing.`Avg Rate Gap`) AS avg_rate_gap FROM " + MV),
    ("How does quoted rate compare to competitor rate by stage?",
     "SELECT mv_pricing.`Salesforce Stage`, MEASURE(mv_pricing.`Avg Quoted Rate`) AS quoted, "
     "MEASURE(mv_pricing.`Avg Competitor Rate`) AS competitor FROM " + MV +
     " GROUP BY mv_pricing.`Salesforce Stage`"),
    ("What is the average fee load by Salesforce stage?",
     "SELECT mv_pricing.`Salesforce Stage`, MEASURE(mv_pricing.`Avg Fee Load`) AS fee_load FROM " + MV +
     " GROUP BY mv_pricing.`Salesforce Stage` ORDER BY fee_load DESC"),
    ("Which stage has the largest rate gap versus market?",
     "SELECT mv_pricing.`Salesforce Stage`, MEASURE(mv_pricing.`Avg Rate Gap`) AS avg_rate_gap FROM " + MV +
     " GROUP BY mv_pricing.`Salesforce Stage` ORDER BY avg_rate_gap DESC LIMIT 1"),
    ("How many opportunities are we quoting above the competitor rate?",
     "SELECT MEASURE(mv_pricing.`Opportunities`) AS opportunities FROM " + MV +
     " WHERE mv_pricing.`Salesforce Stage` IS NOT NULL"),
]
benchmarks = [
    ("What is the average rate gap for Closed Lost opportunities?",
     "SELECT MEASURE(mv_pricing.`Avg Rate Gap`) AS avg_rate_gap FROM " + MV +
     " WHERE mv_pricing.`Salesforce Stage` = 'Closed Lost'", None),
    ("What is the average quoted rate overall?",
     "SELECT MEASURE(mv_pricing.`Avg Quoted Rate`) AS quoted FROM " + MV, None),
    ("Are we systematically overpriced versus the market, and where?", None,
     "Agent must compare Avg Quoted Rate to Avg Competitor Rate (or use Avg Rate Gap) broken down by "
     "Salesforce Stage, cite the numbers, and note that list_rate/fee_load are synthetic while quoted/competitor "
     "rates come from call extraction. Reject if it declares 'overpriced' without the gap evidence."),
]
text_instruction = [
    "## PURPOSE",
    "- Answer account price-posture questions: quoted vs competitor rate, rate gap, fee load.",
    "- Users are Sales/Commercial and Finance leaders.",
    "",
    "## DISAMBIGUATION",
    "- 'Rate gap' = Avg Rate Gap (quoted minus competitor); positive means Superior is above market.",
    "- 'Overpriced' means a positive rate gap, not simply a high quoted rate.",
    "",
    "## DATA QUALITY NOTES",
    "- Quoted and competitor rates are extracted from call transcripts (real); list_rate and fee_load are synthetic.",
    "- rate gap is null when either the quoted or competitor rate was not stated on the call.",
    "",
    "## CONSTRAINTS",
    "- Do not infer a competitor rate when none was extracted; report it as unavailable.",
    "",
    "## Instructions you must follow when providing summaries",
    "- Report rates to 4 decimal places and fee load in USD.",
    "- Note when rate gap excludes opportunities with a missing competitor rate.",
]

def build():
    payload = {
        "version": 2,
        "config": {"sample_questions": sorted(
            [{"id": sid(i), "question": [q]} for i, q in enumerate(sample_questions, 1)], key=lambda x: x["id"])},
        "data_sources": {"metric_views": [{
            "identifier": MV,
            "column_configs": sorted([
                {"column_name": "Salesforce Stage", "enable_entity_matching": True,
                 "synonyms": ["stage", "deal stage"]},
            ], key=lambda c: c["column_name"])}]},
        "instructions": {
            "example_question_sqls": sorted(
                [{"id": eid(i), "question": [q], "sql": [s]} for i, (q, s) in enumerate(example_sqls, 1)], key=lambda x: x["id"]),
            "text_instructions": [{"id": tid(1), "content": text_instruction}]},
        "benchmarks": {"questions": sorted([
            ({"id": bid(i), "question": [q], "answer": [{"format": "SQL", "content": [sql] if sql else []}]}
             | ({"evaluation_note": [note]} if note else {}))
            for i, (q, sql, note) in enumerate(benchmarks, 1)], key=lambda x: x["id"])},
    }
    return json.dumps(payload, indent=2)

if __name__ == "__main__":
    print(build())
