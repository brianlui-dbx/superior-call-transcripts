import { describe, expect, it } from 'vitest';
import { SEED_ROSTER, initCoachingSchema } from '../schema';
import { createFakeDb, type QueryResponder } from './harness';

/** Responds to the roster-count probe with `count`, and succeeds otherwise. */
const responderWithRosterCount =
  (count: number): QueryResponder =>
  (text) => {
    if (text.includes('AS count FROM sales_coaching.salespeople')) {
      return { rows: [{ count }] };
    }
    return { rows: [], rowCount: 1 };
  };

describe('initCoachingSchema', () => {
  it('creates the schema, tables and indexes before seeding', async () => {
    const { db, calls } = createFakeDb(responderWithRosterCount(0));
    await initCoachingSchema(db);

    const text = calls.map((call) => call.text).join('\n');
    expect(text).toContain('CREATE SCHEMA IF NOT EXISTS sales_coaching');
    for (const table of ['salespeople', 'coaching_cases', 'action_items', 'case_feedback', 'case_events']) {
      expect(text).toContain(`CREATE TABLE IF NOT EXISTS sales_coaching.${table}`);
    }
    expect(text).toContain('CREATE INDEX IF NOT EXISTS coaching_cases_status_idx');
  });

  it('seeds the sample roster exactly once, with bound values', async () => {
    const { db, calls } = createFakeDb(responderWithRosterCount(0));
    await initCoachingSchema(db);

    const inserts = calls.filter((call) => call.text.includes('INSERT INTO sales_coaching.salespeople'));
    expect(inserts).toHaveLength(SEED_ROSTER.length);
    expect(inserts[0]?.values).toEqual(['43845461', 'Joshua Harvey MD', 'US-Inside Sales']);
    expect(inserts[0]?.text).toContain('ON CONFLICT (agent_id) DO NOTHING');
  });

  /*
   * The roster is the manager's to curate. Re-seeding a non-empty table would
   * resurrect people they deliberately removed, so seeding is skipped entirely
   * once any row exists.
   */
  it('does not re-seed when the roster already has rows', async () => {
    const { db, calls } = createFakeDb(responderWithRosterCount(3));
    await initCoachingSchema(db);

    const inserts = calls.filter((call) => call.text.includes('INSERT INTO sales_coaching.salespeople'));
    expect(inserts).toHaveLength(0);
  });

  it('propagates a DDL failure so the caller can report it', async () => {
    const { db } = createFakeDb(() => {
      throw new Error('permission denied for schema sales_coaching');
    });
    await expect(initCoachingSchema(db)).rejects.toThrow('permission denied');
  });
});
