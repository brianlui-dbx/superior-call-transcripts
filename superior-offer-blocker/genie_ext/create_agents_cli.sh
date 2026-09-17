#!/usr/bin/env bash
# =============================================================================
# [GENIE ONE EXTENSION] CLI FALLBACK — provision the four extension Genie Agents
# directly with the Databricks CLI (databricks-genie-agents skill pattern), instead
# of the job-based path (resources/genie_one.job.yml). Idempotent: find-by-title →
# update-space, else create-space. Remaps ${catalog}/${schema} placeholders first.
#
# Use this when you'd rather not run the setup job, or to (re)provision a single
# Agent quickly during rehearsal. Requires: databricks CLI, jq.
#
# Usage:
#   PROFILE=dbw-brlui-stable CATALOG=dbw_brlui_stable SCHEMA=call_transcripts_poc \
#   WAREHOUSE_ID=50ad3a9993503e5b ./create_agents_cli.sh
# =============================================================================
set -euo pipefail

: "${PROFILE:?set PROFILE}"; : "${CATALOG:?set CATALOG}"; : "${SCHEMA:?set SCHEMA}"; : "${WAREHOUSE_ID:?set WAREHOUSE_ID}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ME="$(databricks current-user me --profile "$PROFILE" -o json | jq -r '.userName')"
PARENT="/Workspace/Users/${ME}/genie_spaces"
databricks workspace mkdirs "$PARENT" --profile "$PROFILE"

# title|json|description  (description drives Genie One routing — keep vocabulary disjoint)
AGENTS=(
"CX & Service Recovery|genie_cx.json|Contact-center service experience: hold time, queue and abandon, repeat contacts, CSAT, agent/team/skill. Use for how painful the service experience was."
"Delivery Reliability|genie_delivery.json|Propane delivery reliability: verified runouts, late or missed deliveries, gallons, order status. Use for whether we physically failed to serve an account."
"Pricing Position|genie_pricing.json|Account price posture vs market: quoted rate, competitor/current-supplier rate, rate gap, fee load. Use for whether we are priced above market."
"Customer Retention Decision|genie_retention.json|Retention and pricing decisions: raise-vs-protect segmentation, churn-risk tier, contribution and dollars at stake, churn-reduction economics. Use for the strategic which-accounts-to-raise-vs-protect question; this Agent pre-joins the other domains."
)

find_space_id() {  # $1 = title
  local title="$1" token="" out id=""
  while :; do
    if [[ -n "$token" ]]; then
      out="$(databricks api get "/api/2.0/genie/spaces?page_token=${token}" --profile "$PROFILE")"
    else
      out="$(databricks api get "/api/2.0/genie/spaces" --profile "$PROFILE")"
    fi
    id="$(echo "$out" | jq -r --arg t "$title" '.spaces[]? | select(.title==$t) | .space_id' | head -n1)"
    [[ -n "$id" ]] && { echo "$id"; return; }
    token="$(echo "$out" | jq -r '.next_page_token // empty')"
    [[ -z "$token" ]] && { echo ""; return; }
  done
}

for row in "${AGENTS[@]}"; do
  IFS='|' read -r TITLE JSONFILE DESC <<< "$row"
  # Remap catalog/schema placeholders, then flatten to a parsed object and stringify.
  SS="$(sed -e "s/\${catalog}/${CATALOG}/g" -e "s/\${schema}/${SCHEMA}/g" "${HERE}/${JSONFILE}" | jq -c '.' | jq -Rs '.')"
  EXISTING="$(find_space_id "$TITLE")"
  if [[ -n "$EXISTING" ]]; then
    echo ">> updating '$TITLE' ($EXISTING)"
    databricks api patch "/api/2.0/genie/spaces/${EXISTING}" --profile "$PROFILE" --json "$(jq -n \
      --arg t "$TITLE" --arg d "$DESC" --arg w "$WAREHOUSE_ID" --argjson ss "$SS" \
      '{serialized_space:$ss, title:$t, description:$d, warehouse_id:$w}')"
  else
    echo ">> creating '$TITLE'"
    databricks api post "/api/2.0/genie/spaces" --profile "$PROFILE" --json "$(jq -n \
      --arg t "$TITLE" --arg d "$DESC" --arg w "$WAREHOUSE_ID" --arg p "$PARENT" --argjson ss "$SS" \
      '{warehouse_id:$w, title:$t, description:$d, parent_path:$p, serialized_space:$ss}')"
  fi
done
echo "Done. Validate: databricks genie ask -s demo \"Split my NY and NJ book into Can Raise vs Protect and show contribution at risk\" --profile $PROFILE"
