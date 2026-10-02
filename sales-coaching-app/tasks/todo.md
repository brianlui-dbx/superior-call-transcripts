# Sales Manager Coaching App — plan & progress

Approved scope: a sales-manager-facing Databricks App that calls the repo's deployed
Genie agent ("Offer Blocker Analytics") and uses Lakebase for operational serving +
write-back of manager feedback. No existing repo artifact is modified.

Workspace: `dbw-brlui-stable` · Lakebase project: `offer-blocker-coaching` (new)
Genie space: `01f19cba5b581c9a81e28d0502069ec6`

## Decisions locked with the user
- [x] Profile `dbw-brlui-stable`
- [x] New Lakebase project (not reuse)
- [x] Editable, seeded salesperson roster for v1 (pipeline does not expose agent identity to Genie)

## Tasks
- [x] Verify auth, Genie space, AppKit manifest, Lakebase resources
- [x] Create Lakebase project `offer-blocker-coaching` (production branch, primary endpoint)
- [x] Scaffold AppKit app via `databricks apps init --features genie,lakebase`
- [x] Commit scaffold baseline to `feature/customapp`
- [x] Lakebase schema + seeded roster (`sales_coaching`)
- [x] Server: identity, roster, cases, actions, feedback, audit routes (parameterized SQL)
- [x] Client: coaching queue, case workspace, Genie workspace, team roster
- [x] Genie trust: identity, generated SQL, streaming status, disclaimer, execution identity
- [x] Tests (vitest), typecheck, eslint, appkit lint
- [x] Deploy first (SP owns schema), then verify end to end
- [x] Push all commits to remote feature branch

## Review
See "Review" section at the bottom of this file (filled in after implementation).

---

## Review

### What was built
A new Databricks App at `sales-coaching-app/offer-blocker-coach/` (AppKit 0.57.0).
Nothing under `superior-offer-blocker/`, `docs/`, `examples/`, or `original/` was touched —
`git show --stat` for both feature commits lists only paths under `sales-coaching-app/`.

- **Genie (read):** the existing *Offer Blocker Analytics* agent, alias `offerBlockers`,
  executing on behalf of the signed-in manager (`user_api_scopes: [dashboards.genie]`).
- **Lakebase (read/write):** new project `offer-blocker-coaching`, schema `sales_coaching`,
  five tables owned by the app's service principal.
- **Pages:** coaching queue, case workspace, Ask Genie, Team roster.

### Defects found by verification (not by tests alone)
1. **Partial-update data loss.** The Zod helper transformed absent fields to `null`, so a
   status-only PATCH emitted `follow_up_on = NULL, evidence = NULL`. Update schemas now keep
   absent fields `undefined`; an explicit `null` still clears. Regression test added.
2. **Schema init not idempotent for non-owners.** `CREATE INDEX IF NOT EXISTS` checks table
   ownership *before* existence, so local dev failed with `must be owner of table`. Startup now
   probes `information_schema` and skips the DDL when all tables exist.
3. **Off-by-one dates.** Date-only values parsed as UTC then formatted locally rendered a
   follow-up set to the 14th as the 13th. Date-only values now format in UTC.
4. **Wrong text saved as evidence.** Genie returns its narrative in a `text` attachment while
   `message.content` echoes the question, so cases stored the question as evidence.
5. **Governance alert layout** broke each inline element onto its own line; duplicate identity
   badge on the Genie page.

### Verification performed
- 61 vitest tests; typecheck, eslint, `appkit lint`, build, `databricks apps validate` all pass.
- 26 live API assertions against the deployed Lakebase: create, feedback (incl. rating bounds),
  actions, partial-update safety, explicit clear, filters, summary roll-ups, audit trail.
- A live Genie question through the app returned narrative, generated SQL, and result rows.
- All three routes rendered in a browser with no console errors.
- Post-redeploy: app `RUNNING`, deployment `SUCCEEDED`, unauthenticated API correctly `401`,
  and data intact (8 people / 1 case / 1 feedback / 1 action / 7 events).

### Known limitations
- **Salesperson attribution is manual.** The pipeline does not expose `agentId`/`agentName` on
  the gold tables Genie reads, so cases are assigned by the manager. `salespeople.agent_id`
  already exists to automate this if that field is propagated upstream.
- **Lakebase writes are not OBO.** Only `dashboards.genie` is in `user_api_scopes`; Postgres
  writes run as the service principal with the manager's email recorded as author/actor. Adding
  the `postgres` scope would enable per-user connections and row-level security.
- One verification case (#1, a real 4B delivery-fee finding) is left in the database as a
  worked example; it can be dismissed from the UI.
