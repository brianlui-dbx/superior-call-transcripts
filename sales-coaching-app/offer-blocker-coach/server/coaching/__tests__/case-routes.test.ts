import { afterEach, describe, expect, it } from 'vitest';
import type { QueryResultRow } from 'pg';
import { registerCaseRoutes } from '../case-routes';
import {
  createFakeDb,
  findQuery,
  startServer,
  type QueryResponder,
  type RecordedQuery,
  type TestServer,
} from './harness';

const CASE_ROW: QueryResultRow = {
  id: 101,
  salesperson_id: 7,
  salesperson_name: 'Denise Cain',
  salesperson_team: 'US-Inside Sales',
  title: 'Coach on rental fee objection',
  opportunity_id: 'OPP-1',
  blocker_code: '4B',
  blocker_name: 'Ancillary fees',
  disposition: 'friction',
  qualifier: 'rental',
  confidence: 'High',
  evidence: 'Customer balked at the tank rental fee.',
  region: 'New York',
  salesforce_stage: 'Closed Lost',
  status: 'open',
  priority: 'high',
  follow_up_on: '2026-11-01',
  source: 'genie',
  genie_question: 'Which opportunities have fee blockers?',
  genie_answer: 'Three opportunities cite the rental fee.',
  genie_sql: 'SELECT 1',
  genie_conversation_id: 'conv-1',
  created_by: 'manager@example.com',
  created_at: new Date('2026-10-01T12:00:00Z'),
  updated_at: new Date('2026-10-02T09:30:00Z'),
  open_actions: 2,
  feedback_count: 1,
};

/** Routes the fake database by statement shape. */
function responderFor(options: { caseRows?: QueryResultRow[] } = {}): QueryResponder {
  const caseRows = options.caseRows ?? [CASE_ROW];
  return (text) => {
    if (text.includes('INSERT INTO sales_coaching.coaching_cases')) return { rows: [{ id: 101 }] };
    if (text.includes('INSERT INTO sales_coaching.case_feedback')) {
      return {
        rows: [
          {
            id: 5,
            case_id: 101,
            author: 'manager@example.com',
            note: 'Discussed fee framing',
            coaching_rating: 4,
            finding_accurate: true,
            created_at: new Date('2026-10-02T10:00:00Z'),
          },
        ],
      };
    }
    if (text.includes('INSERT INTO sales_coaching.action_items')) {
      return {
        rows: [
          {
            id: 9,
            case_id: 101,
            description: 'Re-quote with fee breakdown',
            owner: 'Denise Cain',
            due_on: '2026-11-05',
            done: false,
            created_by: 'manager@example.com',
            created_at: new Date('2026-10-02T10:05:00Z'),
          },
        ],
      };
    }
    if (text.includes('INSERT INTO sales_coaching.case_events')) return { rows: [] };
    if (text.includes('UPDATE sales_coaching.coaching_cases')) {
      return { rows: caseRows.length > 0 ? [{ id: 101 }] : [] };
    }
    if (text.includes('UPDATE sales_coaching.action_items')) return { rows: [] };
    if (text.includes('DELETE FROM sales_coaching.action_items')) return { rows: [] };
    if (text.includes('FROM sales_coaching.coaching_cases c')) return { rows: caseRows };
    return { rows: [] };
  };
}

let server: TestServer | null = null;

async function serve(responder: QueryResponder): Promise<{ calls: RecordedQuery[]; url: string }> {
  const { db, calls } = createFakeDb(responder);
  server = await startServer(registerCaseRoutes, db);
  return { calls, url: server.url };
}

afterEach(async () => {
  await server?.close();
  server = null;
});

describe('GET /api/coaching-cases', () => {
  it('binds every filter as a parameter instead of inlining it', async () => {
    const { calls, url } = await serve(responderFor());
    const res = await fetch(
      `${url}/api/coaching-cases?status=open&priority=high&salespersonId=7&search=${encodeURIComponent("O'Brien")}`
    );

    expect(res.status).toBe(200);
    const list: unknown = await res.json();
    expect(Array.isArray(list)).toBe(true);

    const query = findQuery(calls, 'FROM sales_coaching.coaching_cases c');
    expect(query.values).toEqual(['open', 'high', 7, "%O'Brien%"]);
    // The raw term must never reach the SQL text.
    expect(query.text).not.toContain("O'Brien");
    expect(query.text).toContain('c.status = $1');
    expect(query.text).toContain('ILIKE $4');
  });

  it('filters to real blockers with a bound disposition array', async () => {
    const { calls, url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases?blockersOnly=true`);

    expect(res.status).toBe(200);
    const query = findQuery(calls, 'FROM sales_coaching.coaching_cases c');
    expect(query.values).toEqual([['hard_blocker', 'friction']]);
    expect(query.text).toContain('c.disposition = ANY($1)');
  });

  it('issues no WHERE clause when unfiltered', async () => {
    const { calls, url } = await serve(responderFor());
    await fetch(`${url}/api/coaching-cases`);

    const query = findQuery(calls, 'FROM sales_coaching.coaching_cases c');
    expect(query.values).toEqual([]);
    // The SELECT's correlated sub-queries legitimately contain WHERE, so assert
    // only that no filter clause follows the join.
    const afterJoin = query.text.split('LEFT JOIN sales_coaching.salespeople')[1] ?? '';
    expect(afterJoin).not.toContain('WHERE');
    expect(afterJoin).toContain('ORDER BY');
  });

  it('rejects an unknown status with 400', async () => {
    const { url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases?status=archived`);
    expect(res.status).toBe(400);
  });

  it('maps rows to the camelCase contract the client expects', async () => {
    const { url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases`);
    const list: unknown = await res.json();

    expect(list).toEqual([
      expect.objectContaining({
        id: 101,
        salespersonName: 'Denise Cain',
        blockerCode: '4B',
        followUpOn: '2026-11-01',
        openActions: 2,
        feedbackCount: 1,
        createdAt: '2026-10-01T12:00:00.000Z',
      }),
    ]);
  });
});

describe('GET /api/coaching-cases/:id', () => {
  it('rejects a non-numeric id', async () => {
    const { url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases/not-a-number`);
    expect(res.status).toBe(400);
  });

  it('returns 404 when the case does not exist', async () => {
    const { url } = await serve(responderFor({ caseRows: [] }));
    const res = await fetch(`${url}/api/coaching-cases/404`);
    expect(res.status).toBe(404);
  });

  it('returns the case with its actions, feedback and audit trail', async () => {
    const { url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases/101`);
    expect(res.status).toBe(200);

    const detail: unknown = await res.json();
    expect(detail).toEqual(expect.objectContaining({ id: 101, actions: [], feedback: [], events: [] }));
  });
});

describe('POST /api/coaching-cases', () => {
  it('rejects a case with no title', async () => {
    const { url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opportunityId: 'OPP-1' }),
    });

    expect(res.status).toBe(400);
    const body: unknown = await res.json();
    expect(body).toEqual({ error: 'title is required' });
  });

  it('persists Genie provenance, attributes the manager, and records an audit event', async () => {
    const { calls, url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-forwarded-email': 'manager@example.com',
      },
      body: JSON.stringify({
        title: 'Coach on rental fee objection',
        salespersonId: 7,
        blockerCode: '4B',
        disposition: 'friction',
        source: 'genie',
        genieQuestion: 'Which opportunities have fee blockers?',
        genieSql: 'SELECT 1',
        genieConversationId: 'conv-1',
      }),
    });

    expect(res.status).toBe(201);

    const insert = findQuery(calls, 'INSERT INTO sales_coaching.coaching_cases');
    expect(insert.values[1]).toBe('Coach on rental fee objection');
    expect(insert.values).toContain('conv-1');
    // created_by is the last bound value.
    expect(insert.values[insert.values.length - 1]).toBe('manager@example.com');

    const event = findQuery(calls, 'INSERT INTO sales_coaching.case_events');
    expect(event.values[0]).toBe(101);
    expect(event.values[1]).toBe('manager@example.com');
    expect(event.values[2]).toBe('case_created');
  });
});

describe('PATCH /api/coaching-cases/:id', () => {
  it('rejects an empty patch', async () => {
    const { url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases/101`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    expect(res.status).toBe(400);
  });

  it('updates only the columns supplied', async () => {
    const { calls, url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases/101`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'resolved' }),
    });

    expect(res.status).toBe(200);
    const update = findQuery(calls, 'UPDATE sales_coaching.coaching_cases');
    expect(update.text).toContain('SET status = $1, updated_at = NOW()');
    expect(update.text).not.toContain('follow_up_on');
    expect(update.values).toEqual(['resolved', 101]);
  });

  it('returns 404 when the case is gone', async () => {
    const { url } = await serve(responderFor({ caseRows: [] }));
    const res = await fetch(`${url}/api/coaching-cases/101`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'resolved' }),
    });
    expect(res.status).toBe(404);
  });
});

describe('POST /api/coaching-cases/:id/feedback', () => {
  it('rejects a rating outside 1-5', async () => {
    const { url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases/101/feedback`, {
      method: 'PATCH'.replace('PATCH', 'POST'),
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: 'Good call', coachingRating: 9 }),
    });
    expect(res.status).toBe(400);
  });

  it('stores the note against the signed-in manager', async () => {
    const { calls, url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases/101/feedback`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-forwarded-email': 'manager@example.com',
      },
      body: JSON.stringify({ note: 'Discussed fee framing', coachingRating: 4, findingAccurate: true }),
    });

    expect(res.status).toBe(201);
    const insert = findQuery(calls, 'INSERT INTO sales_coaching.case_feedback');
    expect(insert.values).toEqual([101, 'manager@example.com', 'Discussed fee framing', 4, true]);

    const body: unknown = await res.json();
    expect(body).toEqual(
      expect.objectContaining({ coachingRating: 4, findingAccurate: true, author: 'manager@example.com' })
    );
  });

  it('falls back to the forwarded user when no email header is present', async () => {
    const { calls, url } = await serve(responderFor());
    await fetch(`${url}/api/coaching-cases/101/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-forwarded-user': 'u-123' },
      body: JSON.stringify({ note: 'Note without email header' }),
    });

    const insert = findQuery(calls, 'INSERT INTO sales_coaching.case_feedback');
    expect(insert.values[1]).toBe('u-123');
  });
});

describe('action items', () => {
  it('adds an action scoped to the case', async () => {
    const { calls, url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases/101/actions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: 'Re-quote with fee breakdown', dueOn: '2026-11-05' }),
    });

    expect(res.status).toBe(201);
    const insert = findQuery(calls, 'INSERT INTO sales_coaching.action_items');
    expect(insert.values[0]).toBe(101);
    expect(insert.values[1]).toBe('Re-quote with fee breakdown');
    expect(insert.values[3]).toBe('2026-11-05');
  });

  it('scopes updates to both the action and its case', async () => {
    const { calls, url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases/101/actions/9`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ done: true }),
    });

    // The fake returns no rows for the update, so a 404 is the correct response.
    expect(res.status).toBe(404);
    const update = findQuery(calls, 'UPDATE sales_coaching.action_items');
    expect(update.text).toContain('WHERE id = $2 AND case_id = $3');
    expect(update.values).toEqual([true, 9, 101]);
  });

  it('returns 404 when deleting an action that is not on the case', async () => {
    const { url } = await serve(responderFor());
    const res = await fetch(`${url}/api/coaching-cases/101/actions/9`, { method: 'DELETE' });
    expect(res.status).toBe(404);
  });
});
