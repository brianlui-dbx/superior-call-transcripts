/**
 * Lakebase schema for coaching state, applied idempotently at startup.
 *
 * The app's service principal must create (and therefore own) this schema, which
 * is why the app is deployed before anyone runs it locally.
 */

import type { CoachingDb } from './db';
import { SCHEMA } from './domain';

/** Synthetic inside-sales roster seeded from the sanitized sample batch. */
const SEED_ROSTER: ReadonlyArray<{ agentId: string; fullName: string; teamName: string }> = [
  { agentId: '43845461', fullName: 'Joshua Harvey MD', teamName: 'US-Inside Sales' },
  { agentId: '43845462', fullName: 'Michael Brooks', teamName: 'US-Inside Sales' },
  { agentId: '43845464', fullName: 'Brian Conner', teamName: 'US-Inside Sales' },
  { agentId: '43845465', fullName: 'Denise Cain', teamName: 'US-Inside Sales' },
  { agentId: '43845467', fullName: 'Todd Barry', teamName: 'US-Inside Sales' },
  { agentId: '43975389', fullName: 'Jason Gonzalez', teamName: 'US-Inside Sales' },
  { agentId: '43975500', fullName: 'Robert Torres', teamName: 'US-Inside Sales' },
  { agentId: '60826431', fullName: 'Elizabeth Newman', teamName: 'US-Inside Sales' },
];

const DDL: readonly string[] = [
  `CREATE SCHEMA IF NOT EXISTS ${SCHEMA}`,

  `CREATE TABLE IF NOT EXISTS ${SCHEMA}.salespeople (
     id          SERIAL PRIMARY KEY,
     agent_id    TEXT UNIQUE,
     full_name   TEXT NOT NULL,
     team_name   TEXT,
     region      TEXT,
     email       TEXT,
     active      BOOLEAN NOT NULL DEFAULT TRUE,
     created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
     updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
   )`,

  `CREATE TABLE IF NOT EXISTS ${SCHEMA}.coaching_cases (
     id                    SERIAL PRIMARY KEY,
     salesperson_id        INTEGER REFERENCES ${SCHEMA}.salespeople(id) ON DELETE SET NULL,
     title                 TEXT NOT NULL,
     opportunity_id        TEXT,
     blocker_code          TEXT,
     blocker_name          TEXT,
     disposition           TEXT,
     qualifier             TEXT,
     confidence            TEXT,
     evidence              TEXT,
     region                TEXT,
     salesforce_stage      TEXT,
     status                TEXT NOT NULL DEFAULT 'open'
                             CHECK (status IN ('open', 'in_coaching', 'resolved', 'dismissed')),
     priority              TEXT NOT NULL DEFAULT 'medium'
                             CHECK (priority IN ('high', 'medium', 'low')),
     follow_up_on          DATE,
     source                TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('genie', 'manual')),
     genie_question        TEXT,
     genie_answer          TEXT,
     genie_sql             TEXT,
     genie_conversation_id TEXT,
     created_by            TEXT,
     created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
     updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
   )`,
  `CREATE INDEX IF NOT EXISTS coaching_cases_status_idx ON ${SCHEMA}.coaching_cases (status)`,
  `CREATE INDEX IF NOT EXISTS coaching_cases_salesperson_idx ON ${SCHEMA}.coaching_cases (salesperson_id)`,
  `CREATE INDEX IF NOT EXISTS coaching_cases_follow_up_idx ON ${SCHEMA}.coaching_cases (follow_up_on)`,

  `CREATE TABLE IF NOT EXISTS ${SCHEMA}.action_items (
     id          SERIAL PRIMARY KEY,
     case_id     INTEGER NOT NULL REFERENCES ${SCHEMA}.coaching_cases(id) ON DELETE CASCADE,
     description TEXT NOT NULL,
     owner       TEXT,
     due_on      DATE,
     done        BOOLEAN NOT NULL DEFAULT FALSE,
     created_by  TEXT,
     created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
     updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
   )`,
  `CREATE INDEX IF NOT EXISTS action_items_case_idx ON ${SCHEMA}.action_items (case_id)`,

  `CREATE TABLE IF NOT EXISTS ${SCHEMA}.case_feedback (
     id               SERIAL PRIMARY KEY,
     case_id          INTEGER NOT NULL REFERENCES ${SCHEMA}.coaching_cases(id) ON DELETE CASCADE,
     author           TEXT,
     note             TEXT NOT NULL,
     coaching_rating  SMALLINT CHECK (coaching_rating BETWEEN 1 AND 5),
     finding_accurate BOOLEAN,
     created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
   )`,
  `CREATE INDEX IF NOT EXISTS case_feedback_case_idx ON ${SCHEMA}.case_feedback (case_id)`,

  `CREATE TABLE IF NOT EXISTS ${SCHEMA}.case_events (
     id         SERIAL PRIMARY KEY,
     case_id    INTEGER NOT NULL REFERENCES ${SCHEMA}.coaching_cases(id) ON DELETE CASCADE,
     actor      TEXT,
     event_type TEXT NOT NULL,
     detail     JSONB,
     created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
   )`,
  `CREATE INDEX IF NOT EXISTS case_events_case_idx ON ${SCHEMA}.case_events (case_id)`,
];

/** Every table `initCoachingSchema` is responsible for creating. */
const EXPECTED_TABLES = ['salespeople', 'coaching_cases', 'action_items', 'case_feedback', 'case_events'] as const;

/**
 * True when every expected table already exists.
 *
 * This probe matters because the DDL above is only *idempotent for the owner*:
 * `CREATE INDEX IF NOT EXISTS` checks table ownership before it checks whether
 * the index exists, so a non-owner re-running it fails with
 * `must be owner of table`. The deployed service principal owns these objects;
 * a developer running locally does not. Skipping the DDL once the schema is in
 * place keeps local runs clean while still letting the service principal create
 * everything on a fresh database.
 *
 * If a later change adds a table this returns false and the DDL runs again,
 * which correctly means such a migration must be applied by a deployment.
 */
async function schemaIsPresent(db: CoachingDb): Promise<boolean> {
  const { rows } = await db.query<{ present: number }>(
    `SELECT CAST(COUNT(*) AS INT) AS present
       FROM information_schema.tables
      WHERE table_schema = $1 AND table_name = ANY($2)`,
    [SCHEMA, [...EXPECTED_TABLES]]
  );
  return (rows[0]?.present ?? 0) === EXPECTED_TABLES.length;
}

/**
 * Seeds the roster only while it is empty, so a manager's later edits and
 * removals are never resurrected by a restart.
 */
async function seedRoster(db: CoachingDb): Promise<number> {
  const { rows } = await db.query<{ count: number }>(
    `SELECT CAST(COUNT(*) AS INT) AS count FROM ${SCHEMA}.salespeople`
  );
  if ((rows[0]?.count ?? 0) > 0) return 0;

  let seeded = 0;
  for (const person of SEED_ROSTER) {
    const result = await db.query(
      `INSERT INTO ${SCHEMA}.salespeople (agent_id, full_name, team_name)
       VALUES ($1, $2, $3)
       ON CONFLICT (agent_id) DO NOTHING`,
      [person.agentId, person.fullName, person.teamName]
    );
    seeded += result.rowCount ?? 0;
  }
  return seeded;
}

/** Applies the schema and seeds the roster. Safe to run on every boot. */
export async function initCoachingSchema(db: CoachingDb): Promise<void> {
  if (await schemaIsPresent(db)) {
    console.log(`[coaching] schema ${SCHEMA} already present, skipping DDL`);
  } else {
    for (const statement of DDL) {
      await db.query(statement);
    }
  }

  const seeded = await seedRoster(db);
  console.log(`[coaching] schema ${SCHEMA} ready${seeded > 0 ? ` (seeded ${seeded} salespeople)` : ''}`);
}

export { EXPECTED_TABLES, SEED_ROSTER };
