/**
 * Roll-ups for the coaching queue header.
 *
 * Every number here is counted from the manager's own coaching state in
 * Lakebase — not from Genie — so the UI can label its provenance honestly.
 */

import type { Application } from 'express';
import type { CoachingDb } from './db';
import { BLOCKING_DISPOSITIONS, SCHEMA } from './domain';
import { fail } from './http';

interface TotalsRow {
  total_cases: number;
  open_cases: number;
  in_coaching_cases: number;
  resolved_30d: number;
  overdue_follow_ups: number;
  created_7d: number;
  open_actions: number;
}

interface BlockerRow {
  blocker_code: string;
  blocker_name: string;
  cases: number;
}

interface SalespersonLoadRow {
  salesperson_id: number;
  full_name: string;
  active_cases: number;
  blocker_cases: number;
  avg_coaching_rating: number | null;
}

export function registerSummaryRoutes(app: Application, db: CoachingDb): void {
  app.get('/api/coaching-summary', async (_req, res) => {
    try {
      const blocking = [...BLOCKING_DISPOSITIONS];

      const [totals, byBlocker, bySalesperson] = await Promise.all([
        db.query<TotalsRow>(
          `SELECT CAST(COUNT(*) AS INT) AS total_cases,
                  CAST(COUNT(*) FILTER (WHERE status = 'open') AS INT) AS open_cases,
                  CAST(COUNT(*) FILTER (WHERE status = 'in_coaching') AS INT) AS in_coaching_cases,
                  CAST(COUNT(*) FILTER (
                        WHERE status = 'resolved' AND updated_at >= NOW() - INTERVAL '30 days'
                      ) AS INT) AS resolved_30d,
                  CAST(COUNT(*) FILTER (
                        WHERE follow_up_on < CURRENT_DATE AND status IN ('open', 'in_coaching')
                      ) AS INT) AS overdue_follow_ups,
                  CAST(COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS INT)
                    AS created_7d,
                  CAST((SELECT COUNT(*) FROM ${SCHEMA}.action_items WHERE NOT done) AS INT)
                    AS open_actions
             FROM ${SCHEMA}.coaching_cases`
        ),
        db.query<BlockerRow>(
          `SELECT COALESCE(blocker_code, 'Unassigned') AS blocker_code,
                  COALESCE(blocker_name, 'No blocker code') AS blocker_name,
                  CAST(COUNT(*) AS INT) AS cases
             FROM ${SCHEMA}.coaching_cases
            WHERE status IN ('open', 'in_coaching')
            GROUP BY 1, 2
            ORDER BY cases DESC, blocker_code`
        ),
        // DISTINCT guards the case counts against fan-out from the feedback join.
        db.query<SalespersonLoadRow>(
          `SELECT s.id AS salesperson_id,
                  s.full_name,
                  CAST(COUNT(DISTINCT c.id) FILTER (
                        WHERE c.status IN ('open', 'in_coaching')
                      ) AS INT) AS active_cases,
                  CAST(COUNT(DISTINCT c.id) FILTER (
                        WHERE c.disposition = ANY($1)
                      ) AS INT) AS blocker_cases,
                  CAST(ROUND(AVG(f.coaching_rating), 2) AS DOUBLE PRECISION)
                    AS avg_coaching_rating
             FROM ${SCHEMA}.salespeople s
             LEFT JOIN ${SCHEMA}.coaching_cases c ON c.salesperson_id = s.id
             LEFT JOIN ${SCHEMA}.case_feedback f ON f.case_id = c.id
            WHERE s.active
            GROUP BY s.id, s.full_name
            ORDER BY active_cases DESC, s.full_name`,
          [blocking]
        ),
      ]);

      const t = totals.rows[0];
      res.json({
        totals: {
          totalCases: t?.total_cases ?? 0,
          openCases: t?.open_cases ?? 0,
          inCoachingCases: t?.in_coaching_cases ?? 0,
          resolvedLast30Days: t?.resolved_30d ?? 0,
          overdueFollowUps: t?.overdue_follow_ups ?? 0,
          createdLast7Days: t?.created_7d ?? 0,
          openActions: t?.open_actions ?? 0,
        },
        byBlocker: byBlocker.rows.map((row) => ({
          blockerCode: row.blocker_code,
          blockerName: row.blocker_name,
          cases: row.cases,
        })),
        bySalesperson: bySalesperson.rows.map((row) => ({
          salespersonId: row.salesperson_id,
          fullName: row.full_name,
          activeCases: row.active_cases,
          blockerCases: row.blocker_cases,
          avgCoachingRating: row.avg_coaching_rating,
        })),
        asOf: new Date().toISOString(),
      });
    } catch (err) {
      fail(res, 'Failed to load coaching summary', err);
    }
  });
}
