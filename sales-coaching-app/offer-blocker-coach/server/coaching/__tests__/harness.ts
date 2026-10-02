/**
 * Test harness: a real Express app plus a programmable fake Lakebase.
 *
 * Using real Express (rather than hand-rolled req/res doubles) means the tests
 * exercise the same routing, JSON body parsing, and status handling the app
 * gets in production, without needing a Postgres connection.
 */

import express, { type Application } from 'express';
import type { AddressInfo } from 'node:net';
import type { QueryResult, QueryResultRow } from 'pg';
import type { CoachingDb } from '../db';

export interface RecordedQuery {
  text: string;
  values: unknown[];
}

export type FakeResult = { rows: QueryResultRow[]; rowCount?: number };

/** Decides what the fake database returns for a given statement. */
export type QueryResponder = (text: string, values: unknown[]) => FakeResult;

export function createFakeDb(responder: QueryResponder): {
  db: CoachingDb;
  calls: RecordedQuery[];
} {
  const calls: RecordedQuery[] = [];

  function query<T extends QueryResultRow = QueryResultRow>(
    text: string,
    values: unknown[] = []
  ): Promise<QueryResult<T>> {
    calls.push({ text, values });
    try {
      const { rows, rowCount } = responder(text, values);
      return Promise.resolve({
        rows: rows as T[],
        rowCount: rowCount ?? rows.length,
        command: 'SELECT',
        oid: 0,
        fields: [],
      });
    } catch (err) {
      // Mirror pg: a failing statement rejects rather than throwing synchronously.
      return Promise.reject(err instanceof Error ? err : new Error(String(err)));
    }
  }

  return { db: { query }, calls };
}

export interface TestServer {
  url: string;
  close: () => Promise<void>;
}

/** Starts the given routes on an ephemeral port. */
export async function startServer(
  register: (app: Application, db: CoachingDb) => void,
  db: CoachingDb
): Promise<TestServer> {
  const app = express();
  app.use(express.json());
  register(app, db);

  const server = app.listen(0);
  await new Promise<void>((resolve) => server.once('listening', resolve));

  const address: string | AddressInfo | null = server.address();
  const port = typeof address === 'object' && address !== null ? address.port : 0;

  return {
    url: `http://127.0.0.1:${port}`,
    close: () => new Promise<void>((resolve, reject) => server.close((err) => (err ? reject(err) : resolve()))),
  };
}

/** Finds the first recorded query whose text contains every fragment. */
export function findQuery(calls: RecordedQuery[], ...fragments: string[]): RecordedQuery {
  const match = calls.find((call) => fragments.every((fragment) => call.text.includes(fragment)));
  if (!match) {
    throw new Error(
      `No query matched [${fragments.join(', ')}]. Recorded:\n${calls
        .map((call) => call.text.replace(/\s+/g, ' ').slice(0, 120))
        .join('\n')}`
    );
  }
  return match;
}
