#!/usr/bin/env python3
"""Build genie_cx.json — CX & Service Recovery Agent (serialized_space v2).
Source: mv_cx_service. Skill-compliant; ids 32-hex lowercase and id-sorted.
Usage: python3 build_genie_cx.py > genie_cx.json
"""
import json
MV = "${catalog}.${schema}.mv_cx_service"
def sid(n): return f"5{n:031x}"
def eid(n): return f"e{n:031x}"
def tid(n): return f"a{n:031x}"
def bid(n): return f"b{n:031x}"

sample_questions = [
    "What is the average hold time and abandon rate by region?",
    "Which teams have the worst abandon rate in NY and NJ?",
    "What is the average CSAT index by team?",
    "How many unmatched (non-sales) contacts did we handle versus matched?",
    "Show contacts and average queue time by skill.",
]
example_sqls = [
    ("What is the average hold time and abandon rate by region?",
     "SELECT mv_cx_service.`Region`, MEASURE(mv_cx_service.`Avg Hold Seconds`) AS avg_hold, "
     "MEASURE(mv_cx_service.`Abandon Rate`) AS abandon_rate FROM " + MV +
     " GROUP BY mv_cx_service.`Region` ORDER BY abandon_rate DESC"),
    ("Which teams have the worst abandon rate in NY and NJ?",
     "SELECT mv_cx_service.`Team`, MEASURE(mv_cx_service.`Abandon Rate`) AS abandon_rate, "
     "MEASURE(mv_cx_service.`Contacts`) AS contacts FROM " + MV +
     " WHERE mv_cx_service.`Region` IN ('New York','New Jersey') "
     "GROUP BY mv_cx_service.`Team` ORDER BY abandon_rate DESC"),
    ("What is the average CSAT index by team?",
     "SELECT mv_cx_service.`Team`, MEASURE(mv_cx_service.`Avg CSAT Index`) AS csat FROM " + MV +
     " GROUP BY mv_cx_service.`Team` ORDER BY csat"),
    ("How many matched vs unmatched contacts are there?",
     "SELECT mv_cx_service.`Match Status`, MEASURE(mv_cx_service.`Contacts`) AS contacts FROM " + MV +
     " GROUP BY mv_cx_service.`Match Status`"),
    ("Show contacts and average queue time by skill.",
     "SELECT mv_cx_service.`Skill`, MEASURE(mv_cx_service.`Contacts`) AS contacts, "
     "MEASURE(mv_cx_service.`Avg Queue Seconds`) AS avg_queue FROM " + MV +
     " GROUP BY mv_cx_service.`Skill` ORDER BY contacts DESC"),
]
benchmarks = [
    ("What is the abandon rate in New York?",
     "SELECT MEASURE(mv_cx_service.`Abandon Rate`) AS abandon_rate FROM " + MV +
     " WHERE mv_cx_service.`Region` = 'New York'", None),
    ("How many contacts were handled by matched opportunities?",
     "SELECT MEASURE(mv_cx_service.`Contacts`) AS contacts FROM " + MV +
     " WHERE mv_cx_service.`Match Status` = 'matched'", None),
    ("Which team most needs service-recovery attention and why?", None,
     "Agent must rank teams by a combination of Abandon Rate and Avg CSAT Index (not one metric alone), "
     "cite the supporting numbers, and name a single team. Reject if it uses only contact volume."),
]
text_instruction = [
    "## PURPOSE",
    "- Answer contact-center service-experience questions for Superior Plus Propane (NY/NJ focus).",
    "- Users are Sales/Ops leaders; assume operational fluency.",
    "",
    "## DISAMBIGUATION",
    "- 'Service problems' means high Avg Hold Seconds, high Abandon Rate, or low Avg CSAT Index.",
    "- 'Matched' contacts tie to a Salesforce opportunity; 'unmatched' do not (Match Status dimension).",
    "",
    "## DATA QUALITY NOTES",
    "- hold/queue/abandon/CSAT are inferred CXone fields and may be null for some calls; averages ignore nulls.",
    "- Transcript-bearing calls are not the full offered-contact population; do not report enterprise abandonment from this alone.",
    "",
    "## CONSTRAINTS",
    "- Scope to New York and New Jersey unless another region is named.",
    "",
    "## Instructions you must follow when providing summaries",
    "- State the region and team scope used in the summary.",
    "- Report rates as percentages and hold/queue as seconds.",
]

def build():
    payload = {
        "version": 2,
        "config": {"sample_questions": sorted(
            [{"id": sid(i), "question": [q]} for i, q in enumerate(sample_questions, 1)], key=lambda x: x["id"])},
        "data_sources": {"metric_views": [{
            "identifier": MV,
            "column_configs": sorted([
                {"column_name": "Region", "enable_format_assistance": True, "enable_entity_matching": True,
                 "synonyms": ["state", "market"]},
                {"column_name": "Team", "enable_entity_matching": True},
                {"column_name": "Match Status", "enable_entity_matching": True,
                 "description": ["matched = call tied to a Salesforce opportunity; unmatched = no opp."]},
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
