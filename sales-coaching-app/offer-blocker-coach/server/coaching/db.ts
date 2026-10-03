/**
 * Narrow structural views of the AppKit handles the coaching routes need.
 *
 * Keeping these minimal means the route modules can be unit-tested against a
 * fake database without standing up a Lakebase pool, while the call site in
 * `server.ts` still type-checks against the real plugin exports.
 */

import type { Application, Request } from 'express';
import type { QueryResult, QueryResultRow } from 'pg';

export interface CoachingDb {
  query<T extends QueryResultRow = QueryResultRow>(text: string, values?: unknown[]): Promise<QueryResult<T>>;
}

export interface CoachingAppKit {
  lakebase: CoachingDb;
  server: { extend(fn: (app: Application) => void): void };
}

/**
 * The signed-in manager, from the identity headers Databricks Apps injects.
 *
 * Recorded as the author/actor on everything written to Lakebase so coaching
 * history is attributable even though the writes themselves run as the app's
 * service principal.
 */
export function actorFrom(req: Request): string | null {
  return req.header('x-forwarded-email') ?? req.header('x-forwarded-user') ?? null;
}

/** Parses a positive integer route parameter, or `null` when it is not one. */
export function parseId(raw: string | undefined): number | null {
  if (!raw) return null;
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/**
 * Builds the `SET` clause of an UPDATE from a column → value map, skipping keys
 * the caller did not supply. Column names are literals from the route module,
 * never user input; values are always bound as parameters.
 */
export function buildUpdate(
  columns: Record<string, unknown>,
  firstParamIndex = 1
): { clause: string; values: unknown[] } {
  const assignments: string[] = [];
  const values: unknown[] = [];
  for (const [column, value] of Object.entries(columns)) {
    if (value === undefined) continue;
    values.push(value);
    assignments.push(`${column} = $${firstParamIndex + values.length - 1}`);
  }
  return { clause: assignments.join(', '), values };
}

/** Records an entry in the per-case audit trail. Never throws into a request. */
export async function recordEvent(
  db: CoachingDb,
  schema: string,
  caseId: number,
  actor: string | null,
  eventType: string,
  detail: Record<string, unknown> = {}
): Promise<void> {
  try {
    await db.query(
      `INSERT INTO ${schema}.case_events (case_id, actor, event_type, detail)
       VALUES ($1, $2, $3, $4::jsonb)`,
      [caseId, actor, eventType, JSON.stringify(detail)]
    );
  } catch (err) {
    console.error('[coaching] failed to record case event', eventType, err);
  }
}
