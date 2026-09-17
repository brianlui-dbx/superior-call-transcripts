#!/usr/bin/env python3
"""Build genie_delivery.json — Delivery Reliability Agent (serialized_space v2).
Source: mv_delivery. Skill-compliant; ids 32-hex lowercase and id-sorted.
Usage: python3 build_genie_delivery.py > genie_delivery.json
"""
import json
MV = "${catalog}.${schema}.mv_delivery"
def sid(n): return f"5{n:031x}"
def eid(n): return f"e{n:031x}"
def tid(n): return f"a{n:031x}"
def bid(n): return f"b{n:031x}"

sample_questions = [
    "What is the runout rate by month?",
    "How many verified service failures did we have in the last 90 days?",
    "What is the late delivery rate by order status?",
    "How many total gallons did we deliver by month?",
    "Which month had the worst runout rate?",
]
example_sqls = [
    ("What is the runout rate by month?",
     "SELECT mv_delivery.`Delivery Month`, MEASURE(mv_delivery.`Runout Rate`) AS runout_rate FROM " + MV +
     " GROUP BY mv_delivery.`Delivery Month` ORDER BY mv_delivery.`Delivery Month`"),
    ("How many verified service failures in total?",
     "SELECT MEASURE(mv_delivery.`Verified Failures`) AS failures FROM " + MV),
    ("What is the late delivery rate by order status?",
     "SELECT mv_delivery.`Order Status`, MEASURE(mv_delivery.`Late Delivery Rate`) AS late_rate, "
     "MEASURE(mv_delivery.`Orders`) AS orders FROM " + MV +
     " GROUP BY mv_delivery.`Order Status` ORDER BY late_rate DESC"),
    ("How many total gallons did we deliver by month?",
     "SELECT mv_delivery.`Delivery Month`, MEASURE(mv_delivery.`Total Gallons`) AS gallons FROM " + MV +
     " GROUP BY mv_delivery.`Delivery Month` ORDER BY mv_delivery.`Delivery Month`"),
    ("Which month had the worst runout rate?",
     "SELECT mv_delivery.`Delivery Month`, MEASURE(mv_delivery.`Runout Rate`) AS runout_rate FROM " + MV +
     " GROUP BY mv_delivery.`Delivery Month` ORDER BY runout_rate DESC LIMIT 1"),
]
benchmarks = [
    ("What is the overall verified runout rate?",
     "SELECT MEASURE(mv_delivery.`Runout Rate`) AS runout_rate FROM " + MV, None),
    ("How many verified failures occurred among emergency orders?",
     "SELECT MEASURE(mv_delivery.`Verified Failures`) AS failures FROM " + MV +
     " WHERE mv_delivery.`Order Status` = 'emergency'", None),
    ("Is delivery reliability getting better or worse, and where is the risk concentrated?", None,
     "Agent must compare Runout Rate and Late Delivery Rate across Delivery Month (trend), cite the numbers, "
     "and note that values are synthetic. Reject if it claims a trend without month-over-month evidence."),
]
text_instruction = [
    "## PURPOSE",
    "- Answer propane delivery-reliability questions: runouts, late deliveries, gallons.",
    "- Users are Operations leaders; assume logistics fluency.",
    "",
    "## DISAMBIGUATION",
    "- 'Service failure' means a verified runout OR a late delivery (Verified Failures measure).",
    "- 'Runout' counts only when runout_verified_flag = 1 (an operational record); never infer from complaints.",
    "",
    "## DATA QUALITY NOTES",
    "- All delivery values are synthetic (is_synthetic = true); present them as illustrative.",
    "",
    "## CONSTRAINTS",
    "- Do not attribute a runout to an account without a verified delivery record.",
    "",
    "## Instructions you must follow when providing summaries",
    "- State the date range used and that the figures are synthetic/illustrative.",
    "- Report runout and late rates as percentages.",
]

def build():
    payload = {
        "version": 2,
        "config": {"sample_questions": sorted(
            [{"id": sid(i), "question": [q]} for i, q in enumerate(sample_questions, 1)], key=lambda x: x["id"])},
        "data_sources": {"metric_views": [{
            "identifier": MV,
            "column_configs": sorted([
                {"column_name": "Order Status", "enable_entity_matching": True,
                 "description": ["on_time, late, or emergency (a verified runout)."]},
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
