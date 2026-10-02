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
