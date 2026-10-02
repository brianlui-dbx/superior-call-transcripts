# Offer Blocker Coach

A sales-manager-facing Databricks App that turns the offer-blocker intelligence in this
repository into coached, tracked follow-up.

- **Genie** — the existing **Offer Blocker Analytics** agent answers natural-language questions
  about blockers, call tone, quoted rates, and drafted follow-up emails.
- **Lakebase** — every manager decision (assignment, status, coaching notes, agreed actions) is
  persisted to Postgres for operational serving.

Nothing in the pipeline, dashboard, Genie definition, or `superior-offer-blocker/` bundle is
modified by this app.

## What a manager does here

| Page | Purpose |
|---|---|
| **Coaching queue** (`/`) | Headline counts, active cases by blocker code, load per salesperson, and a filterable case list (status, rep, real-blockers-only, free-text search). |
| **Case workspace** (`/cases/:id`) | The finding and its evidence, the Genie provenance it came from, coaching notes with two ratings, agreed actions, and an audit trail. |
| **Ask Genie** (`/genie`) | Curated coaching questions plus free-form chat, the generated SQL for every answer, and one click to open a coaching case from an answer. |
| **Team** (`/team`) | The salesperson roster — add, edit, deactivate. |

## Architecture

```text
Sales manager (browser)
        │
        ├── /api/genie/offerBlockers/…  → AppKit genie plugin → Genie agent → SQL warehouse
        │       runs ON BEHALF OF the signed-in user (user_api_scopes: dashboards.genie)
        │
        └── /api/coaching-cases, /api/salespeople, /api/coaching-summary
                → AppKit lakebase plugin → Lakebase Postgres (schema `sales_coaching`)
                  runs as the app's service principal, attributed to the signed-in user
```

Genie is the read path for lakehouse analysis; Lakebase is the read/write path for coaching
state. The app deliberately does not query Unity Catalog directly.

## Databricks resources

| Resource | Value |
|---|---|
| Workspace | `adb-7405605163137288.8.azuredatabricks.net` |
| Genie space | `01f19cba5b581c9a81e28d0502069ec6` (*Offer Blocker Analytics*) |
| Lakebase project | `projects/offer-blocker-coaching` |
| Lakebase branch | `projects/offer-blocker-coaching/branches/production` |
| Lakebase database | `databricks-postgres` (schema `sales_coaching`) |

## Lakebase schema

Created idempotently at startup by the app's service principal.

| Table | Holds |
|---|---|
| `salespeople` | The roster. Seeded once from the sample batch, then manager-owned. |
| `coaching_cases` | One case per blocker being coached, plus its Genie provenance. |
| `action_items` | Commitments from the coaching conversation. |
| `case_feedback` | Append-only coaching notes, a 1–5 handling rating, and a verdict on whether the AI finding was correct. |
| `case_events` | Audit trail of every change. |

### Salesperson attribution

The raw transcript files carry `agentId` / `agentName`, but the current pipeline does not surface
them on the gold tables Genie reads, so a finding cannot be attributed to a rep automatically.
The roster is therefore seeded from the sanitized sample batch and the manager assigns cases.
If `agentId` is later propagated into `gold_offer_blocker_summary`, assignment can be automated
against the `salespeople.agent_id` column that already exists for that purpose.

## Deploy

Deploy **before** running locally — the service principal must create and own the
`sales_coaching` schema. Running `npm run dev` first makes your own identity the owner and the
deployed app then fails with `permission denied`.

```bash
PROFILE=dbw-brlui-stable

databricks apps validate --profile "$PROFILE"
databricks bundle deploy --profile "$PROFILE"       # from this directory
databricks apps get offer-blocker-coach --profile "$PROFILE" -o json   # expect RUNNING + url
databricks apps logs offer-blocker-coach --profile "$PROFILE"          # OAuth profiles only
```

## Local development

After the app has been deployed at least once:

```bash
npm install
npm run dev      # http://localhost:8000
```

`.env` is written by `databricks apps init` and is gitignored. Locally, identity headers are
absent, so coaching entries are attributed to `null` and Genie runs with your CLI credentials.

## Checks

```bash
npm run typecheck      # server + client
npm run lint           # eslint
npm run lint:ast-grep  # appkit lint (AppKit anti-patterns)
npm test               # vitest — 52 tests
npm run build          # server bundle + client bundle
```

Tests cover the validation contract, the three-state PATCH semantics (absent vs. explicit null),
SQL parameter binding, schema/seed idempotency, and the HTTP behaviour of every route against a
fake Lakebase, using real Express.
