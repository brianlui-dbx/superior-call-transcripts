import { afterEach, describe, expect, it } from 'vitest';
import { registerRosterRoutes } from '../roster-routes';
import {
  createFakeDb,
  findQuery,
  startServer,
  type QueryResponder,
  type RecordedQuery,
  type TestServer,
} from './harness';

const PERSON = {
  id: 7,
  agent_id: '43845465',
  full_name: 'Denise Cain',
  team_name: 'US-Inside Sales',
  region: 'New York',
  email: null,
  active: true,
};

let server: TestServer | null = null;

async function serve(responder: QueryResponder): Promise<{ calls: RecordedQuery[]; url: string }> {
  const { db, calls } = createFakeDb(responder);
  server = await startServer(registerRosterRoutes, db);
  return { calls, url: server.url };
}

afterEach(async () => {
  await server?.close();
  server = null;
});

describe('GET /api/salespeople', () => {
  it('returns only active people by default', async () => {
    const { calls, url } = await serve(() => ({ rows: [PERSON] }));
    const res = await fetch(`${url}/api/salespeople`);

    expect(res.status).toBe(200);
    expect(findQuery(calls, 'FROM sales_coaching.salespeople').text).toContain('WHERE active');

    const body: unknown = await res.json();
    expect(body).toEqual([
      {
        id: 7,
        agentId: '43845465',
        fullName: 'Denise Cain',
        teamName: 'US-Inside Sales',
        region: 'New York',
        email: null,
        active: true,
      },
    ]);
  });

  it('includes inactive people when asked', async () => {
    const { calls, url } = await serve(() => ({ rows: [PERSON] }));
    await fetch(`${url}/api/salespeople?includeInactive=true`);
    expect(findQuery(calls, 'FROM sales_coaching.salespeople').text).not.toContain('WHERE active');
  });
});

describe('POST /api/salespeople', () => {
  it('requires a name', async () => {
    const { url } = await serve(() => ({ rows: [PERSON] }));
    const res = await fetch(`${url}/api/salespeople`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ teamName: 'US-Inside Sales' }),
    });

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'fullName is required' });
  });

  it('maps a duplicate agent id to 409 rather than a 500', async () => {
    const { url } = await serve(() => {
      throw Object.assign(new Error('duplicate key'), { code: '23505' });
    });
    const res = await fetch(`${url}/api/salespeople`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fullName: 'Denise Cain', agentId: '43845465' }),
    });

    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ error: 'That agent ID is already on the roster' });
  });
});

describe('PATCH /api/salespeople/:id', () => {
  it('deactivates without touching the other columns', async () => {
    const { calls, url } = await serve(() => ({ rows: [{ ...PERSON, active: false }] }));
    const res = await fetch(`${url}/api/salespeople/7`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active: false }),
    });

    expect(res.status).toBe(200);
    const update = findQuery(calls, 'UPDATE sales_coaching.salespeople');
    expect(update.text).toContain('SET active = $1, updated_at = NOW()');
    // RETURNING lists every column, so scope the check to the SET clause.
    const setClause = update.text.split('RETURNING')[0] ?? '';
    expect(setClause).not.toContain('full_name');
    expect(update.values).toEqual([false, 7]);
  });

  it('rejects an empty patch', async () => {
    const { url } = await serve(() => ({ rows: [PERSON] }));
    const res = await fetch(`${url}/api/salespeople/7`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    expect(res.status).toBe(400);
  });

  it('404s when the row does not exist', async () => {
    const { url } = await serve(() => ({ rows: [] }));
    const res = await fetch(`${url}/api/salespeople/99`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active: true }),
    });
    expect(res.status).toBe(404);
  });
});
