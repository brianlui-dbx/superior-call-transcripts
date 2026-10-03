/**
 * Typed client for the app's own Express routes.
 *
 * Coaching state is read and written here (Lakebase); Genie answers arrive
 * separately over the AppKit Genie SSE stream.
 */

export type CaseStatus = 'open' | 'in_coaching' | 'resolved' | 'dismissed';
export type CasePriority = 'high' | 'medium' | 'low';

export interface Salesperson {
  id: number;
  agentId: string | null;
  fullName: string;
  teamName: string | null;
  region: string | null;
  email: string | null;
  active: boolean;
}

export interface CoachingCase {
  id: number;
  salespersonId: number | null;
  salespersonName: string | null;
  salespersonTeam: string | null;
  title: string;
  opportunityId: string | null;
  blockerCode: string | null;
  blockerName: string | null;
  disposition: string | null;
  qualifier: string | null;
  confidence: string | null;
  evidence: string | null;
  region: string | null;
  salesforceStage: string | null;
  status: CaseStatus;
  priority: CasePriority;
  followUpOn: string | null;
  source: 'genie' | 'manual';
  genieQuestion: string | null;
  genieAnswer: string | null;
  genieSql: string | null;
  genieConversationId: string | null;
  createdBy: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  openActions: number;
  feedbackCount: number;
}

export interface ActionItem {
  id: number;
  caseId: number;
  description: string;
  owner: string | null;
  dueOn: string | null;
  done: boolean;
  createdBy: string | null;
  createdAt: string | null;
}

export interface CaseFeedback {
  id: number;
  caseId: number;
  author: string | null;
  note: string;
  coachingRating: number | null;
  findingAccurate: boolean | null;
  createdAt: string | null;
}

export interface CaseEvent {
  id: number;
  actor: string | null;
  eventType: string;
  detail: Record<string, unknown>;
  createdAt: string | null;
}

export interface CaseDetail extends CoachingCase {
  actions: ActionItem[];
  feedback: CaseFeedback[];
  events: CaseEvent[];
}

export interface CoachingSummary {
  totals: {
    totalCases: number;
    openCases: number;
    inCoachingCases: number;
    resolvedLast30Days: number;
    overdueFollowUps: number;
    createdLast7Days: number;
    openActions: number;
  };
  byBlocker: { blockerCode: string; blockerName: string; cases: number }[];
  bySalesperson: {
    salespersonId: number;
    fullName: string;
    activeCases: number;
    blockerCases: number;
    avgCoachingRating: number | null;
  }[];
  asOf: string;
}

export interface Identity {
  email: string | null;
  user: string | null;
  actor: string | null;
  genieExecution: string;
  lakebaseExecution: string;
}

export interface CaseFilters {
  status?: CaseStatus;
  priority?: CasePriority;
  salespersonId?: number;
  blockersOnly?: boolean;
  search?: string;
}

export interface NewCase {
  salespersonId: number | null;
  title: string;
  opportunityId?: string | null;
  blockerCode?: string | null;
  blockerName?: string | null;
  disposition?: string | null;
  evidence?: string | null;
  region?: string | null;
  salesforceStage?: string | null;
  priority: CasePriority;
  followUpOn?: string | null;
  source: 'genie' | 'manual';
  genieQuestion?: string | null;
  genieAnswer?: string | null;
  genieSql?: string | null;
  genieConversationId?: string | null;
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === 'object' && 'error' in body && typeof body.error === 'string') {
      return body.error;
    }
  } catch {
    // Non-JSON error body — fall through to the status text.
  }
  return `Request failed (${res.status})`;
}

async function send(path: string, method: string, body?: unknown): Promise<Response> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res;
}

async function json<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const res = await send(path, method, body);
  const data: unknown = await res.json();
  return data as T;
}

function queryString(filters: CaseFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set('status', filters.status);
  if (filters.priority) params.set('priority', filters.priority);
  if (filters.salespersonId !== undefined) {
    params.set('salespersonId', String(filters.salespersonId));
  }
  if (filters.blockersOnly) params.set('blockersOnly', 'true');
  if (filters.search) params.set('search', filters.search);
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

export const api = {
  whoami: () => json<Identity>('/api/whoami'),
  summary: () => json<CoachingSummary>('/api/coaching-summary'),

  listSalespeople: (includeInactive = false) =>
    json<Salesperson[]>(`/api/salespeople${includeInactive ? '?includeInactive=true' : ''}`),
  addSalesperson: (input: {
    fullName: string;
    agentId?: string | null;
    teamName?: string | null;
    region?: string | null;
    email?: string | null;
  }) => json<Salesperson>('/api/salespeople', 'POST', input),
  updateSalesperson: (id: number, input: Partial<Omit<Salesperson, 'id'>>) =>
    json<Salesperson>(`/api/salespeople/${id}`, 'PATCH', input),

  listCases: (filters: CaseFilters = {}) => json<CoachingCase[]>(`/api/coaching-cases${queryString(filters)}`),
  getCase: (id: number) => json<CaseDetail>(`/api/coaching-cases/${id}`),
  createCase: (input: NewCase) => json<CaseDetail>('/api/coaching-cases', 'POST', input),
  updateCase: (
    id: number,
    input: Partial<Pick<CoachingCase, 'status' | 'priority' | 'title' | 'evidence'>> & {
      salespersonId?: number | null;
      followUpOn?: string | null;
    }
  ) => json<CaseDetail>(`/api/coaching-cases/${id}`, 'PATCH', input),

  addFeedback: (
    caseId: number,
    input: { note: string; coachingRating?: number | null; findingAccurate?: boolean | null }
  ) => json<CaseFeedback>(`/api/coaching-cases/${caseId}/feedback`, 'POST', input),

  addAction: (caseId: number, input: { description: string; owner?: string | null; dueOn?: string | null }) =>
    json<ActionItem>(`/api/coaching-cases/${caseId}/actions`, 'POST', input),
  updateAction: (
    caseId: number,
    actionId: number,
    input: { done?: boolean; description?: string; owner?: string | null; dueOn?: string | null }
  ) => json<ActionItem>(`/api/coaching-cases/${caseId}/actions/${actionId}`, 'PATCH', input),
  removeAction: async (caseId: number, actionId: number): Promise<void> => {
    await send(`/api/coaching-cases/${caseId}/actions/${actionId}`, 'DELETE');
  },
};
