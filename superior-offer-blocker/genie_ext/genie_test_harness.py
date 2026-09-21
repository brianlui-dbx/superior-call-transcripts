#!/usr/bin/env python3
"""Genie One talk-track validation harness.

Starts a conversation on a target Genie space, polls to completion, and prints
the text answer + generated SQL + row count. Uses the Databricks CLI's
`api` passthrough against a named profile (no SDK dependency).

Usage:
  python3 genie_test_harness.py --profile dbw-brlui-stable-cc [--only 3]
"""
import argparse, json, subprocess, sys, time, textwrap

PROFILE_DEFAULT = "dbw-brlui-stable-cc"

# space_id per live agent (from `databricks api get /api/2.0/genie/spaces`)
SPACES = {
    "offer_blocker":  "01f1b5f88115180288c3d88f02cb21e4",
    "cx":             "01f1b3c91e0e13febf1ba4aeab396269",
    "delivery":       "01f1b3c91e051d90b565ff2c64d62ec2",
    "pricing":        "01f1b3c91a571453854248562a3ee2c5",
    "retention":      "01f1b3c91afb13ad9863842bfc2648da",
}

# The 7 talk-track prompts, each with the Agent it SHOULD route to.
TALK_TRACK = [
    (1, "offer_blocker",
     "Which offer blockers are driving the most Closed Lost opportunity value in New York and New Jersey, and how does rate competitiveness (4A) rank?"),
    (2, "cx",
     "For opportunities in NY and NJ, show average hold time, abandon rate, and repeat-contact rate by region and team."),
    (3, "retention",
     "List NY and NJ opportunities that have a rate objection (4A) AND a verified runout or late delivery in the last 90 days. Rank by opportunity value and show the churn-risk tier."),
    (4, "retention",
     "For those at-risk opportunities, how far above the competitor rate are we quoting, and what is their fee load?"),
    (5, "retention",
     "Split my NY and NJ book into two segments: accounts that can absorb a price increase (healthy CSAT, no runouts, small rate gap) versus accounts I must protect. Show the churn-risk tier and the evidence behind each."),
    (6, "retention",
     "Draft a retention-first outreach for the top 5 protect accounts, referencing the specific service issue (runout or late delivery) on each. Review only, do not send."),
    (7, "retention",
     "Using the illustrative 100,000-account scenario at $600 contribution per retained account and $150,000 program cost, show net annual contribution at 0.5, 1, and 2 points of churn reduction, and the break-even. Label every assumption."),
]


def api(profile, method, path, body=None):
    cmd = ["databricks", "api", method.lower(), path, "-p", profile]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"api {method} {path} failed: {r.stderr.strip()}")
    out = r.stdout.strip()
    return json.loads(out) if out else {}


def ask(profile, space_id, question, timeout=180):
    """Start a conversation and poll to completion. Returns the message dict."""
    start = api(profile, "post",
                f"/api/2.0/genie/spaces/{space_id}/start-conversation",
                {"content": question})
    conv_id = start["conversation_id"]
    msg_id = start["message_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        msg = api(profile, "get",
                  f"/api/2.0/genie/spaces/{space_id}/conversations/{conv_id}/messages/{msg_id}")
        status = msg.get("status")
        if status in ("COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"):
            return conv_id, msg_id, msg
        time.sleep(3)
    return conv_id, msg_id, {"status": "TIMEOUT"}


def get_query_result(profile, space_id, conv_id, msg_id, attachment_id):
    try:
        return api(profile, "get",
                   f"/api/2.0/genie/spaces/{space_id}/conversations/{conv_id}/messages/{msg_id}/attachments/{attachment_id}/query-result")
    except Exception as e:
        return {"error": str(e)}


def summarize(profile, space_id, conv_id, msg_id, msg):
    """Pull text answer, SQL, and row count out of the message attachments."""
    text_parts, sql_parts, rowcounts = [], [], []
    for att in msg.get("attachments", []) or []:
        if "text" in att and att["text"]:
            text_parts.append(att["text"].get("content", ""))
        if "query" in att and att["query"]:
            q = att["query"]
            sql_parts.append(q.get("query", ""))
            att_id = att.get("attachment_id")
            if att_id:
                qr = get_query_result(profile, space_id, conv_id, msg_id, att_id)
                sr = (qr.get("statement_response") or {})
                n = ((sr.get("result") or {}).get("row_count"))
                if n is None:
                    n = (((sr.get("manifest") or {}).get("total_row_count")))
                rowcounts.append(n)
    return "\n".join(text_parts), "\n---\n".join(sql_parts), rowcounts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=PROFILE_DEFAULT)
    ap.add_argument("--only", type=int, default=None, help="run only question N")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    results = []
    for num, expected_agent, q in TALK_TRACK:
        if args.only and num != args.only:
            continue
        space_id = SPACES[expected_agent]
        print("=" * 90)
        print(f"Q{num}  (expected route: {expected_agent})")
        print(textwrap.fill(q, 88, initial_indent="  ", subsequent_indent="  "))
        print("-" * 90)
        try:
            conv_id, msg_id, msg = ask(args.profile, space_id, q, args.timeout)
            status = msg.get("status")
            text, sql, rowcounts = summarize(args.profile, space_id, conv_id, msg_id, msg)
            print(f"STATUS: {status}   rows: {rowcounts}")
            if text:
                print("ANSWER:")
                print(textwrap.indent(text.strip()[:1400], "    "))
            if sql:
                print("SQL:")
                print(textwrap.indent(sql.strip()[:1200], "    "))
            results.append((num, expected_agent, status, rowcounts, text[:200]))
        except Exception as e:
            print(f"ERROR: {e}")
            results.append((num, expected_agent, "ERROR", [], str(e)[:200]))

    print("\n" + "=" * 90)
    print("SUMMARY")
    for num, agent, status, rowcounts, _ in results:
        print(f"  Q{num:<2} {agent:<14} {status:<12} rows={rowcounts}")


if __name__ == "__main__":
    main()
