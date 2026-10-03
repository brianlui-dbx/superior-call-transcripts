/**
 * Coaching cases: the manager's operational record for one offer-blocker
 * finding — who it belongs to, where it stands, what was said in coaching, and
 * what the rep agreed to do next.
 *
 * Genie provenance (question, answer, generated SQL, conversation) is stored
 * alongside the case so a coaching conversation can always be traced back to
 * the analysis that triggered it.
 */

import type { Application } from 'express';
import { actorFrom, buildUpdate, parseId, recordEvent, type CoachingDb } from './db';
import {
  BLOCKING_DISPOSITIONS,
  CaseListQuery,
  CreateActionBody,
  CreateCaseBody,
  CreateFeedbackBody,
  SCHEMA,
  UpdateActionBody,
  UpdateCaseBody,
} from './domain';
import { fail, iso, parseOr400 } from './http';

interface CaseRow {
  id: number;
  salesperson_id: number | null;
  salesperson_name: string | null;
  salesperson_team: string | null;
  title: string;
  opportunity_id: string | null;
  blocker_code: string | null;
  blocker_name: string | null;
  disposition: string | null;
  qualifier: string | null;
  confidence: string | null;
  evidence: string | null;
  region: string | null;
  salesforce_stage: string | null;
  status: string;
  priority: string;
  follow_up_on: string | null;
  source: string;
  genie_question: string | null;
  genie_answer: string | null;
  genie_sql: string | null;
  genie_conversation_id: string | null;
  created_by: string | null;
  created_at: Date;
  updated_at: Date;
  open_actions: number;
  feedback_count: number;
}

interface ActionRow {
  id: number;
  case_id: number;
  description: string;
  owner: string | null;
  due_on: string | null;
  done: boolean;
  created_by: string | null;
  created_at: Date;
}

interface FeedbackRow {
  id: number;
  case_id: number;
  author: string | null;
  note: string;
  coaching_rating: number | null;
  finding_accurate: boolean | null;
  created_at: Date;
}

interface EventRow {
  id: number;
  actor: string | null;
  event_type: string;
  detail: Record<string, unknown> | null;
  created_at: Date;
}

/**
 * DATE columns are rendered as text so they survive the trip without a
 * timezone shift; bigint counts are cast to int so they arrive as numbers.
 */
const CASE_SELECT = `
  SELECT c.id, c.salesperson_id, c.title, c.opportunity_id, c.blocker_code, c.blocker_name,
         c.disposition, c.qualifier, c.confidence, c.evidence, c.region, c.salesforce_stage,
         c.status, c.priority, TO_CHAR(c.follow_up_on, 'YYYY-MM-DD') AS follow_up_on,
         c.source, c.genie_question, c.genie_answer, c.genie_sql, c.genie_conversation_id,
         c.created_by, c.created_at, c.updated_at,
         s.full_name AS salesperson_name, s.team_name AS salesperson_team,
         CAST((SELECT COUNT(*) FROM ${SCHEMA}.action_items a
                WHERE a.case_id = c.id AND NOT a.done) AS INT) AS open_actions,
         CAST((SELECT COUNT(*) FROM ${SCHEMA}.case_feedback f
                WHERE f.case_id = c.id) AS INT) AS feedback_count
    FROM ${SCHEMA}.coaching_cases c
    LEFT JOIN ${SCHEMA}.salespeople s ON s.id = c.salesperson_id`;

function toCase(row: CaseRow) {
  return {
    id: row.id,
    salespersonId: row.salesperson_id,
    salespersonName: row.salesperson_name,
    salespersonTeam: row.salesperson_team,
    title: row.title,
    opportunityId: row.opportunity_id,
    blockerCode: row.blocker_code,
    blockerName: row.blocker_name,
    disposition: row.disposition,
    qualifier: row.qualifier,
    confidence: row.confidence,
    evidence: row.evidence,
    region: row.region,
    salesforceStage: row.salesforce_stage,
    status: row.status,
    priority: row.priority,
    followUpOn: row.follow_up_on,
    source: row.source,
    genieQuestion: row.genie_question,
    genieAnswer: row.genie_answer,
    genieSql: row.genie_sql,
    genieConversationId: row.genie_conversation_id,
    createdBy: row.created_by,
    createdAt: iso(row.created_at),
    updatedAt: iso(row.updated_at),
    openActions: row.open_actions,
    feedbackCount: row.feedback_count,
  };
}

const toAction = (row: ActionRow) => ({
  id: row.id,
  caseId: row.case_id,
  description: row.description,
  owner: row.owner,
  dueOn: row.due_on,
  done: row.done,
  createdBy: row.created_by,
  createdAt: iso(row.created_at),
});

const toFeedback = (row: FeedbackRow) => ({
  id: row.id,
  caseId: row.case_id,
  author: row.author,
  note: row.note,
  coachingRating: row.coaching_rating,
  findingAccurate: row.finding_accurate,
  createdAt: iso(row.created_at),
});

const toEvent = (row: EventRow) => ({
  id: row.id,
  actor: row.actor,
  eventType: row.event_type,
  detail: row.detail ?? {},
  createdAt: iso(row.created_at),
});

const ACTION_COLUMNS = `id, case_id, description, owner, TO_CHAR(due_on, 'YYYY-MM-DD') AS due_on,
                        done, created_by, created_at`;

/** Loads a case with its actions, coaching feedback, and audit trail. */
async function loadCaseDetail(db: CoachingDb, id: number) {
  const { rows } = await db.query<CaseRow>(`${CASE_SELECT} WHERE c.id = $1`, [id]);
  const found = rows[0];
  if (!found) return null;

  const [actions, feedback, events] = await Promise.all([
    db.query<ActionRow>(
      `SELECT ${ACTION_COLUMNS} FROM ${SCHEMA}.action_items
        WHERE case_id = $1 ORDER BY done, due_on NULLS LAST, id`,
      [id]
    ),
    db.query<FeedbackRow>(
      `SELECT id, case_id, author, note, coaching_rating, finding_accurate, created_at
         FROM ${SCHEMA}.case_feedback WHERE case_id = $1 ORDER BY created_at DESC`,
      [id]
    ),
    db.query<EventRow>(
      `SELECT id, actor, event_type, detail, created_at
         FROM ${SCHEMA}.case_events WHERE case_id = $1 ORDER BY created_at DESC LIMIT 50`,
      [id]
    ),
  ]);

  return {
    ...toCase(found),
    actions: actions.rows.map(toAction),
    feedback: feedback.rows.map(toFeedback),
    events: events.rows.map(toEvent),
  };
}

export function registerCaseRoutes(app: Application, db: CoachingDb): void {
  app.get('/api/coaching-cases', async (req, res) => {
    const filters = parseOr400(CaseListQuery, req.query, res);
    if (!filters) return;

    const conditions: string[] = [];
    const values: unknown[] = [];
    const bind = (value: unknown) => {
      values.push(value);
      return `$${values.length}`;
    };

    if (filters.status) conditions.push(`c.status = ${bind(filters.status)}`);
    if (filters.priority) conditions.push(`c.priority = ${bind(filters.priority)}`);
    if (filters.salespersonId !== undefined) {
      conditions.push(`c.salesperson_id = ${bind(filters.salespersonId)}`);
    }
    if (filters.blockersOnly) {
      conditions.push(`c.disposition = ANY(${bind([...BLOCKING_DISPOSITIONS])})`);
    }
    if (filters.search) {
      const term = bind(`%${filters.search}%`);
      conditions.push(
        `(c.title ILIKE ${term} OR c.opportunity_id ILIKE ${term} OR c.evidence ILIKE ${term}
          OR c.blocker_name ILIKE ${term} OR s.full_name ILIKE ${term})`
      );
    }

    const where = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';
    try {
      const { rows } = await db.query<CaseRow>(
        `${CASE_SELECT}
         ${where}
         ORDER BY CASE c.status WHEN 'open' THEN 0 WHEN 'in_coaching' THEN 1 ELSE 2 END,
                  CASE c.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                  c.follow_up_on NULLS LAST,
                  c.created_at DESC
         LIMIT 200`,
        values
      );
      res.json(rows.map(toCase));
    } catch (err) {
      fail(res, 'Failed to list coaching cases', err);
    }
  });

  app.get('/api/coaching-cases/:id', async (req, res) => {
    const id = parseId(req.params.id);
    if (id === null) {
      res.status(400).json({ error: 'Invalid id' });
      return;
    }
    try {
      const detail = await loadCaseDetail(db, id);
      if (!detail) {
        res.status(404).json({ error: 'Coaching case not found' });
        return;
      }
      res.json(detail);
    } catch (err) {
      fail(res, 'Failed to load coaching case', err);
    }
  });

  app.post('/api/coaching-cases', async (req, res) => {
    const input = parseOr400(CreateCaseBody, req.body, res);
    if (!input) return;
    const actor = actorFrom(req);

    try {
      const { rows } = await db.query<{ id: number }>(
        `INSERT INTO ${SCHEMA}.coaching_cases
           (salesperson_id, title, opportunity_id, blocker_code, blocker_name, disposition,
            qualifier, confidence, evidence, region, salesforce_stage, status, priority,
            follow_up_on, source, genie_question, genie_answer, genie_sql,
            genie_conversation_id, created_by)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17,
                 $18, $19, $20)
         RETURNING id`,
        [
          input.salespersonId,
          input.title,
          input.opportunityId,
          input.blockerCode,
          input.blockerName,
          input.disposition,
          input.qualifier,
          input.confidence,
          input.evidence,
          input.region,
          input.salesforceStage,
          input.status,
          input.priority,
          input.followUpOn,
          input.source,
          input.genieQuestion,
          input.genieAnswer,
          input.genieSql,
          input.genieConversationId,
          actor,
        ]
      );
      const created = rows[0];
      if (!created) {
        fail(res, 'Failed to create coaching case', new Error('insert returned no row'));
        return;
      }

      await recordEvent(db, SCHEMA, created.id, actor, 'case_created', {
        source: input.source,
        status: input.status,
        priority: input.priority,
      });
      res.status(201).json(await loadCaseDetail(db, created.id));
    } catch (err) {
      if (isForeignKeyViolation(err)) {
        res.status(400).json({ error: 'That salesperson is not on the roster' });
        return;
      }
      fail(res, 'Failed to create coaching case', err);
    }
  });

  app.patch('/api/coaching-cases/:id', async (req, res) => {
    const id = parseId(req.params.id);
    if (id === null) {
      res.status(400).json({ error: 'Invalid id' });
      return;
    }
    const input = parseOr400(UpdateCaseBody, req.body, res);
    if (!input) return;

    const { clause, values } = buildUpdate({
      salesperson_id: input.salespersonId,
      title: input.title,
      status: input.status,
      priority: input.priority,
      follow_up_on: input.followUpOn,
      evidence: input.evidence,
    });
    if (!clause) {
      res.status(400).json({ error: 'no fields to update' });
      return;
    }

    try {
      const { rows } = await db.query<{ id: number }>(
        `UPDATE ${SCHEMA}.coaching_cases SET ${clause}, updated_at = NOW()
          WHERE id = $${values.length + 1}
          RETURNING id`,
        [...values, id]
      );
      if (!rows[0]) {
        res.status(404).json({ error: 'Coaching case not found' });
        return;
      }
      await recordEvent(db, SCHEMA, id, actorFrom(req), 'case_updated', { ...input });
      res.json(await loadCaseDetail(db, id));
    } catch (err) {
      if (isForeignKeyViolation(err)) {
        res.status(400).json({ error: 'That salesperson is not on the roster' });
        return;
      }
      fail(res, 'Failed to update coaching case', err);
    }
  });

  app.post('/api/coaching-cases/:id/feedback', async (req, res) => {
    const id = parseId(req.params.id);
    if (id === null) {
      res.status(400).json({ error: 'Invalid id' });
      return;
    }
    const input = parseOr400(CreateFeedbackBody, req.body, res);
    if (!input) return;
    const actor = actorFrom(req);

    try {
      const { rows } = await db.query<FeedbackRow>(
        `INSERT INTO ${SCHEMA}.case_feedback (case_id, author, note, coaching_rating, finding_accurate)
         VALUES ($1, $2, $3, $4, $5)
         RETURNING id, case_id, author, note, coaching_rating, finding_accurate, created_at`,
        [id, actor, input.note, input.coachingRating, input.findingAccurate]
      );
      const created = rows[0];
      if (!created) {
        fail(res, 'Failed to save feedback', new Error('insert returned no row'));
        return;
      }
      await recordEvent(db, SCHEMA, id, actor, 'feedback_added', {
        coachingRating: input.coachingRating,
        findingAccurate: input.findingAccurate,
      });
      res.status(201).json(toFeedback(created));
    } catch (err) {
      if (isForeignKeyViolation(err)) {
        res.status(404).json({ error: 'Coaching case not found' });
        return;
      }
      fail(res, 'Failed to save feedback', err);
    }
  });

  app.post('/api/coaching-cases/:id/actions', async (req, res) => {
    const id = parseId(req.params.id);
    if (id === null) {
      res.status(400).json({ error: 'Invalid id' });
      return;
    }
    const input = parseOr400(CreateActionBody, req.body, res);
    if (!input) return;
    const actor = actorFrom(req);

    try {
      const { rows } = await db.query<ActionRow>(
        `INSERT INTO ${SCHEMA}.action_items (case_id, description, owner, due_on, created_by)
         VALUES ($1, $2, $3, $4, $5)
         RETURNING ${ACTION_COLUMNS}`,
        [id, input.description, input.owner, input.dueOn, actor]
      );
      const created = rows[0];
      if (!created) {
        fail(res, 'Failed to add action item', new Error('insert returned no row'));
        return;
      }
      await recordEvent(db, SCHEMA, id, actor, 'action_added', { description: input.description });
      res.status(201).json(toAction(created));
    } catch (err) {
      if (isForeignKeyViolation(err)) {
        res.status(404).json({ error: 'Coaching case not found' });
        return;
      }
      fail(res, 'Failed to add action item', err);
    }
  });

  app.patch('/api/coaching-cases/:id/actions/:actionId', async (req, res) => {
    const caseId = parseId(req.params.id);
    const actionId = parseId(req.params.actionId);
    if (caseId === null || actionId === null) {
      res.status(400).json({ error: 'Invalid id' });
      return;
    }
    const input = parseOr400(UpdateActionBody, req.body, res);
    if (!input) return;

    const { clause, values } = buildUpdate({
      description: input.description,
      owner: input.owner,
      due_on: input.dueOn,
      done: input.done,
    });
    if (!clause) {
      res.status(400).json({ error: 'no fields to update' });
      return;
    }

    try {
      const { rows } = await db.query<ActionRow>(
        `UPDATE ${SCHEMA}.action_items SET ${clause}, updated_at = NOW()
          WHERE id = $${values.length + 1} AND case_id = $${values.length + 2}
          RETURNING ${ACTION_COLUMNS}`,
        [...values, actionId, caseId]
      );
      const updated = rows[0];
      if (!updated) {
        res.status(404).json({ error: 'Action item not found' });
        return;
      }
      await recordEvent(db, SCHEMA, caseId, actorFrom(req), 'action_updated', {
        actionId,
        ...input,
      });
      res.json(toAction(updated));
    } catch (err) {
      fail(res, 'Failed to update action item', err);
    }
  });

  app.delete('/api/coaching-cases/:id/actions/:actionId', async (req, res) => {
    const caseId = parseId(req.params.id);
    const actionId = parseId(req.params.actionId);
    if (caseId === null || actionId === null) {
      res.status(400).json({ error: 'Invalid id' });
      return;
    }
    try {
      const { rows } = await db.query<{ id: number }>(
        `DELETE FROM ${SCHEMA}.action_items WHERE id = $1 AND case_id = $2 RETURNING id`,
        [actionId, caseId]
      );
      if (!rows[0]) {
        res.status(404).json({ error: 'Action item not found' });
        return;
      }
      await recordEvent(db, SCHEMA, caseId, actorFrom(req), 'action_removed', { actionId });
      res.status(204).send();
    } catch (err) {
      fail(res, 'Failed to remove action item', err);
    }
  });
}

/** Postgres foreign-key violation — e.g. a salesperson or case id that is gone. */
function isForeignKeyViolation(err: unknown): boolean {
  return typeof err === 'object' && err !== null && 'code' in err && err.code === '23503';
}

export { loadCaseDetail, toCase };
