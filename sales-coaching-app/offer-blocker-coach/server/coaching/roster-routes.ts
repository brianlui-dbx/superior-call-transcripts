/**
 * Salesperson roster.
 *
 * The upstream pipeline does not expose the agent identity captured in the raw
 * transcripts to the Genie tables, so the roster is seeded from the sample batch
 * and then owned by the manager: they can add, correct, or deactivate people.
 */

import type { Application } from 'express';
import { actorFrom, parseId, buildUpdate, type CoachingDb } from './db';
import { CreateSalespersonBody, SCHEMA, UpdateSalespersonBody } from './domain';
import { fail, parseOr400 } from './http';

interface SalespersonRow {
  id: number;
  agent_id: string | null;
  full_name: string;
  team_name: string | null;
  region: string | null;
  email: string | null;
  active: boolean;
}

const COLUMNS = 'id, agent_id, full_name, team_name, region, email, active';

function toSalesperson(row: SalespersonRow) {
  return {
    id: row.id,
    agentId: row.agent_id,
    fullName: row.full_name,
    teamName: row.team_name,
    region: row.region,
    email: row.email,
    active: row.active,
  };
}

export function registerRosterRoutes(app: Application, db: CoachingDb): void {
  app.get('/api/salespeople', async (req, res) => {
    try {
      const includeInactive = req.query.includeInactive === 'true';
      const { rows } = await db.query<SalespersonRow>(
        `SELECT ${COLUMNS} FROM ${SCHEMA}.salespeople
         ${includeInactive ? '' : 'WHERE active'}
         ORDER BY full_name`
      );
      res.json(rows.map(toSalesperson));
    } catch (err) {
      fail(res, 'Failed to list salespeople', err);
    }
  });

  app.post('/api/salespeople', async (req, res) => {
    const input = parseOr400(CreateSalespersonBody, req.body, res);
    if (!input) return;
    try {
      const { rows } = await db.query<SalespersonRow>(
        `INSERT INTO ${SCHEMA}.salespeople (full_name, agent_id, team_name, region, email)
         VALUES ($1, $2, $3, $4, $5)
         RETURNING ${COLUMNS}`,
        [input.fullName, input.agentId, input.teamName, input.region, input.email]
      );
      const created = rows[0];
      if (!created) {
        fail(res, 'Failed to add salesperson', new Error('insert returned no row'));
        return;
      }
      console.log(`[coaching] ${actorFrom(req) ?? 'unknown'} added salesperson ${created.id}`);
      res.status(201).json(toSalesperson(created));
    } catch (err) {
      if (isUniqueViolation(err)) {
        res.status(409).json({ error: 'That agent ID is already on the roster' });
        return;
      }
      fail(res, 'Failed to add salesperson', err);
    }
  });

  app.patch('/api/salespeople/:id', async (req, res) => {
    const id = parseId(req.params.id);
    if (id === null) {
      res.status(400).json({ error: 'Invalid id' });
      return;
    }
    const input = parseOr400(UpdateSalespersonBody, req.body, res);
    if (!input) return;

    const { clause, values } = buildUpdate({
      full_name: input.fullName,
      agent_id: input.agentId,
      team_name: input.teamName,
      region: input.region,
      email: input.email,
      active: input.active,
    });
    if (!clause) {
      res.status(400).json({ error: 'no fields to update' });
      return;
    }

    try {
      const { rows } = await db.query<SalespersonRow>(
        `UPDATE ${SCHEMA}.salespeople SET ${clause}, updated_at = NOW()
         WHERE id = $${values.length + 1}
         RETURNING ${COLUMNS}`,
        [...values, id]
      );
      const updated = rows[0];
      if (!updated) {
        res.status(404).json({ error: 'Salesperson not found' });
        return;
      }
      res.json(toSalesperson(updated));
    } catch (err) {
      if (isUniqueViolation(err)) {
        res.status(409).json({ error: 'That agent ID is already on the roster' });
        return;
      }
      fail(res, 'Failed to update salesperson', err);
    }
  });
}

/** Postgres unique-constraint violation. */
function isUniqueViolation(err: unknown): boolean {
  return typeof err === 'object' && err !== null && 'code' in err && err.code === '23505';
}
