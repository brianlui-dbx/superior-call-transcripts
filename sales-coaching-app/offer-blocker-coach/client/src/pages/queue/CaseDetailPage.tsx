import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Checkbox,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Separator,
  Skeleton,
  Textarea,
} from '@databricks/appkit-ui/react';
import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import { ArrowLeft, ChevronDown, Trash2 } from 'lucide-react';
import { api, type CaseDetail, type CasePriority, type CaseStatus, type Salesperson } from '@/lib/api';
import { dispositionLabel, formatDate, formatDateTime, isOverdue, todayISO } from '@/lib/format';
import { DispositionBadge, OverdueBadge, PriorityBadge, StatusBadge } from '@/components/badges';

const UNASSIGNED = 'unassigned';
const NONE = 'none';

export function CaseDetailPage() {
  const params = useParams();
  const caseId = Number(params.id);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [salespeople, setSalespeople] = useState<Salesperson[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setDetail(await api.getCase(caseId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load this coaching case');
    }
  }, [caseId]);

  useEffect(() => {
    if (!Number.isInteger(caseId) || caseId <= 0) {
      setError('That case id is not valid.');
      return;
    }
    void load();
  }, [caseId, load]);

  useEffect(() => {
    api
      .listSalespeople()
      .then(setSalespeople)
      .catch(() => setSalespeople([]));
  }, []);

  /** Every control writes straight through to Lakebase and re-reads the case. */
  const patch = async (input: Parameters<typeof api.updateCase>[1]) => {
    setSaving(true);
    try {
      setDetail(await api.updateCase(caseId, input));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save your change');
    } finally {
      setSaving(false);
    }
  };

  if (error && !detail) {
    return (
      <div className="mx-auto w-full max-w-3xl space-y-4">
        <BackLink />
        <Alert variant="destructive">
          <AlertTitle>Could not open this case</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="mx-auto w-full max-w-5xl space-y-4">
        <BackLink />
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4">
      <BackLink />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-2xl font-semibold text-foreground">{detail.title}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Case #{detail.id} · {detail.salespersonName ?? 'Unassigned'}
            {detail.salespersonTeam ? ` · ${detail.salespersonTeam}` : ''} · created {formatDateTime(detail.createdAt)}
            {detail.createdBy ? ` by ${detail.createdBy}` : ''}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={detail.status} />
          <PriorityBadge priority={detail.priority} />
          <DispositionBadge disposition={detail.disposition} />
          {isOverdue(detail.followUpOn, detail.status) && <OverdueBadge />}
          <Badge variant="outline" className="text-muted-foreground">
            {detail.source === 'genie' ? 'From Genie' : 'Manual'}
          </Badge>
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">The finding</CardTitle>
              <CardDescription>Extracted from the call transcript by the offer-blocker pipeline.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <dl className="grid gap-3 sm:grid-cols-2">
                <Detail label="Opportunity">{detail.opportunityId ?? '—'}</Detail>
                <Detail label="Blocker">
                  {detail.blockerCode ? `${detail.blockerCode} · ${detail.blockerName ?? ''}` : 'Not coded'}
                </Detail>
                <Detail label="Impact">{dispositionLabel(detail.disposition)}</Detail>
                <Detail label="Qualifier">{detail.qualifier ?? '—'}</Detail>
                <Detail label="Confidence">{detail.confidence ?? '—'}</Detail>
                <Detail label="Region">{detail.region ?? '—'}</Detail>
                <Detail label="Salesforce stage">{detail.salesforceStage ?? '—'}</Detail>
                <Detail label="Follow-up">{formatDate(detail.followUpOn)}</Detail>
              </dl>
              <Separator />
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Evidence</p>
                <p className="mt-1 whitespace-pre-wrap">{detail.evidence ?? 'No evidence captured on this case.'}</p>
              </div>
            </CardContent>
          </Card>

          {(detail.genieQuestion ?? detail.genieAnswer ?? detail.genieSql) && (
            <Card>
              <Collapsible>
                <CardHeader className="pb-3">
                  <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 text-left">
                    <div>
                      <CardTitle className="text-base">Genie provenance</CardTitle>
                      <CardDescription>The question, answer and SQL this case came from.</CardDescription>
                    </div>
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                  </CollapsibleTrigger>
                </CardHeader>
                <CollapsibleContent>
                  <CardContent className="space-y-3 text-sm">
                    {detail.genieQuestion && (
                      <div>
                        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Question asked
                        </p>
                        <p className="mt-1">{detail.genieQuestion}</p>
                      </div>
                    )}
                    {detail.genieAnswer && (
                      <div>
                        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Genie answer
                        </p>
                        <p className="mt-1 whitespace-pre-wrap">{detail.genieAnswer}</p>
                      </div>
                    )}
                    {detail.genieSql && (
                      <div>
                        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Generated SQL
                        </p>
                        <pre className="mt-1 max-h-56 overflow-auto rounded-md bg-muted p-3 text-xs">
                          {detail.genieSql}
                        </pre>
                      </div>
                    )}
                    <p className="text-xs text-muted-foreground">
                      AI-generated — verify against the SQL before coaching on it.
                    </p>
                  </CardContent>
                </CollapsibleContent>
              </Collapsible>
            </Card>
          )}

          <FeedbackCard detail={detail} onSaved={load} />
          <ActionsCard detail={detail} onChanged={load} />
          <ActivityCard detail={detail} />
        </div>

        <Card className="h-fit">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Coaching status</CardTitle>
            <CardDescription>Saved to Lakebase as you change it.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="detail-status">Status</Label>
              <Select value={detail.status} onValueChange={(value) => void patch({ status: value as CaseStatus })}>
                <SelectTrigger id="detail-status" disabled={saving}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="open">Open</SelectItem>
                  <SelectItem value="in_coaching">In coaching</SelectItem>
                  <SelectItem value="resolved">Resolved</SelectItem>
                  <SelectItem value="dismissed">Dismissed</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="detail-priority">Priority</Label>
              <Select
                value={detail.priority}
                onValueChange={(value) => void patch({ priority: value as CasePriority })}
              >
                <SelectTrigger id="detail-priority" disabled={saving}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="low">Low</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="detail-rep">Salesperson</Label>
              <Select
                value={detail.salespersonId === null ? UNASSIGNED : String(detail.salespersonId)}
                onValueChange={(value) => void patch({ salespersonId: value === UNASSIGNED ? null : Number(value) })}
              >
                <SelectTrigger id="detail-rep" disabled={saving}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={UNASSIGNED}>Unassigned</SelectItem>
                  {salespeople.map((person) => (
                    <SelectItem key={person.id} value={String(person.id)}>
                      {person.fullName}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="detail-followup">Follow up on</Label>
              <Input
                id="detail-followup"
                type="date"
                disabled={saving}
                value={detail.followUpOn ?? ''}
                onChange={(e) => void patch({ followUpOn: e.target.value || null })}
              />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function BackLink() {
  return (
    <Link to="/" className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="mr-1 h-4 w-4" />
      Back to coaching queue
    </Link>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 break-words">{children}</dd>
    </div>
  );
}

/** The manager's coaching record: an append-only note trail with two ratings. */
function FeedbackCard({ detail, onSaved }: { detail: CaseDetail; onSaved: () => Promise<void> }) {
  const [note, setNote] = useState('');
  const [rating, setRating] = useState(NONE);
  const [accurate, setAccurate] = useState(NONE);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!note.trim()) {
      setError('Add a note before saving.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.addFeedback(detail.id, {
        note: note.trim(),
        coachingRating: rating === NONE ? null : Number(rating),
        findingAccurate: accurate === NONE ? null : accurate === 'yes',
      });
      setNote('');
      setRating(NONE);
      setAccurate(NONE);
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save your feedback');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Coaching notes &amp; feedback</CardTitle>
        <CardDescription>
          What you discussed with the rep, and whether the AI finding was right. Stored in Lakebase and attributed to
          you.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={(event) => void submit(event)} className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="feedback-note">Coaching note</Label>
            <Textarea
              id="feedback-note"
              rows={4}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Walked through reframing the tank rental fee against annual delivery savings."
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="feedback-rating">How the rep handled it</Label>
              <Select value={rating} onValueChange={setRating}>
                <SelectTrigger id="feedback-rating">
                  <SelectValue placeholder="Not rated" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>Not rated</SelectItem>
                  <SelectItem value="1">1 — needs significant work</SelectItem>
                  <SelectItem value="2">2 — below expectations</SelectItem>
                  <SelectItem value="3">3 — met expectations</SelectItem>
                  <SelectItem value="4">4 — strong</SelectItem>
                  <SelectItem value="5">5 — exemplary</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="feedback-accurate">Was the AI finding accurate?</Label>
              <Select value={accurate} onValueChange={setAccurate}>
                <SelectTrigger id="feedback-accurate">
                  <SelectValue placeholder="No verdict" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>No verdict</SelectItem>
                  <SelectItem value="yes">Yes — matches the call</SelectItem>
                  <SelectItem value="no">No — misclassified</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <Button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Save feedback'}
          </Button>
        </form>

        <Separator />

        {detail.feedback.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>No coaching recorded yet</EmptyTitle>
              <EmptyDescription>Your first note will start the coaching history for this blocker.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ul className="space-y-3">
            {detail.feedback.map((entry) => (
              <li key={entry.id} className="rounded-md border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>{entry.author ?? 'Unknown author'}</span>
                  <span>·</span>
                  <span>{formatDateTime(entry.createdAt)}</span>
                  {entry.coachingRating !== null && (
                    <Badge variant="secondary">{entry.coachingRating}/5 handling</Badge>
                  )}
                  {entry.findingAccurate !== null && (
                    <Badge variant={entry.findingAccurate ? 'secondary' : 'destructive'}>
                      {entry.findingAccurate ? 'Finding accurate' : 'Finding wrong'}
                    </Badge>
                  )}
                </div>
                <p className="mt-2 whitespace-pre-wrap">{entry.note}</p>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** What the rep agreed to do next. */
function ActionsCard({ detail, onChanged }: { detail: CaseDetail; onChanged: () => Promise<void> }) {
  const [description, setDescription] = useState('');
  const [owner, setOwner] = useState('');
  const [dueOn, setDueOn] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (operation: () => Promise<unknown>, message: string) => {
    setBusy(true);
    setError(null);
    try {
      await operation();
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : message);
    } finally {
      setBusy(false);
    }
  };

  const add = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!description.trim()) {
      setError('Describe the action before adding it.');
      return;
    }
    await run(async () => {
      await api.addAction(detail.id, {
        description: description.trim(),
        owner: owner.trim() || detail.salespersonName,
        dueOn: dueOn || null,
      });
      setDescription('');
      setOwner('');
      setDueOn('');
    }, 'Failed to add the action item');
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Agreed actions</CardTitle>
        <CardDescription>Commitments from the coaching conversation.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          onSubmit={(event) => void add(event)}
          className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto]"
        >
          <div className="space-y-2">
            <Label htmlFor="action-description">Action</Label>
            <Input
              id="action-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Re-quote with the fee breakdown attached"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="action-due">Due</Label>
            <Input
              id="action-due"
              type="date"
              min={todayISO()}
              value={dueOn}
              onChange={(e) => setDueOn(e.target.value)}
            />
          </div>
          <div className="flex items-end">
            <Button type="submit" variant="outline" disabled={busy}>
              Add
            </Button>
          </div>
        </form>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {detail.actions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No actions agreed yet.</p>
        ) : (
          <ul className="space-y-2">
            {detail.actions.map((action) => (
              <li key={action.id} className="flex items-start gap-3 rounded-md border p-3 text-sm">
                <Checkbox
                  id={`action-${action.id}`}
                  checked={action.done}
                  disabled={busy}
                  onCheckedChange={(checked) =>
                    void run(
                      () => api.updateAction(detail.id, action.id, { done: checked === true }),
                      'Failed to update the action item'
                    )
                  }
                />
                <div className="min-w-0 flex-1">
                  <Label
                    htmlFor={`action-${action.id}`}
                    className={action.done ? 'text-muted-foreground line-through' : ''}
                  >
                    {action.description}
                  </Label>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {action.owner ?? 'Unassigned'} · due {formatDate(action.dueOn)}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  aria-label="Remove action item"
                  onClick={() =>
                    void run(() => api.removeAction(detail.id, action.id), 'Failed to remove the action item')
                  }
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

const EVENT_LABELS: Record<string, string> = {
  case_created: 'Case created',
  case_updated: 'Case updated',
  feedback_added: 'Coaching feedback added',
  action_added: 'Action added',
  action_updated: 'Action updated',
  action_removed: 'Action removed',
};

function ActivityCard({ detail }: { detail: CaseDetail }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Activity</CardTitle>
        <CardDescription>Audit trail for this case, newest first.</CardDescription>
      </CardHeader>
      <CardContent>
        {detail.events.length === 0 ? (
          <p className="text-sm text-muted-foreground">No activity recorded.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {detail.events.map((event) => (
              <li key={event.id} className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-medium">{EVENT_LABELS[event.eventType] ?? event.eventType}</span>
                <span className="text-xs text-muted-foreground">
                  {event.actor ?? 'system'} · {formatDateTime(event.createdAt)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
