/** Wires the coaching schema and every coaching route onto the AppKit server. */

import type { CoachingAppKit } from './db';
import { actorFrom } from './db';
import { registerCaseRoutes } from './case-routes';
import { registerRosterRoutes } from './roster-routes';
import { registerSummaryRoutes } from './summary-routes';
import { initCoachingSchema } from './schema';

export async function setupCoaching(appkit: CoachingAppKit): Promise<void> {
  const db = appkit.lakebase;

  try {
    await initCoachingSchema(db);
  } catch (err) {
    // Routes are still registered so the UI can show a real error instead of a
    // blank page. The usual cause is schema ownership — see README.
    console.error('[coaching] schema init failed; coaching routes will return errors:', err);
  }

  appkit.server.extend((app) => {
    /**
     * Identity of the signed-in manager, used for the header badge and to
     * disclose how each half of the app executes.
     */
    app.get('/api/whoami', (req, res) => {
      res.json({
        email: req.header('x-forwarded-email') ?? null,
        user: req.header('x-forwarded-user') ?? null,
        actor: actorFrom(req),
        /** Genie runs on behalf of the user: `user_api_scopes: [dashboards.genie]`. */
        genieExecution: 'on_behalf_of_user',
        /** Lakebase writes run as the app's service principal, attributed to `actor`. */
        lakebaseExecution: 'service_principal',
      });
    });

    registerSummaryRoutes(app, db);
    registerRosterRoutes(app, db);
    registerCaseRoutes(app, db);
  });
}
