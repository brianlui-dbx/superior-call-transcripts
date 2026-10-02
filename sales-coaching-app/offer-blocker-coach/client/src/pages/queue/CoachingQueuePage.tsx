import {
  Alert,
  AlertDescription,
  AlertTitle,
  BarChart,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
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
  Skeleton,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@databricks/appkit-ui/react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { CirclePlus } from 'lucide-react';
import {
  api,
  type CaseFilters,
  type CaseStatus,
  type CoachingCase,
  type CoachingSummary,
  type Salesperson,
} from '@/lib/api';
import { formatDate, formatTime, isOverdue } from '@/lib/format';
import { DispositionBadge, OverdueBadge, PriorityBadge, StatusBadge } from '@/components/badges';
import { KpiTile } from '@/components/KpiTile';
import { CaseFormDialog } from '@/components/CaseFormDialog';

const ALL = 'all';

export function CoachingQueuePage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<CoachingSummary | null>(null);
  const [cases, setCases] = useState<CoachingCase[] | null>(null);
  const [salespeople, setSalespeople] = useState<Salesperson[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string>(ALL);
  const [salespersonId, setSalespersonId] = useState<string>(ALL);
  const [blockersOnly, setBlockersOnly] = useState(false);
  const [search, setSearch] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);

  const filters: CaseFilters = useMemo(
    () => ({
      status: status === ALL ? undefined : (status as CaseStatus),
      salespersonId: salespersonId === ALL ? undefined : Number(salespersonId),
      blockersOnly,
      search: search.trim() || undefined,
    }),
    [status, salespersonId, blockersOnly, search]
  );

  const refresh = useCallback(async () => {
    try {
      const [summaryResult, caseResult] = await Promise.all([api.summary(), api.listCases(filters)]);
      setSummary(summaryResult);
      setCases(caseResult);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load the coaching queue');
      setCases([]);
    }
  }, [filters]);

  useEffect(() => {
    api
      .listSalespeople()
      .then(setSalespeople)
      .catch(() => setSalespeople([]));
  }, []);

  // Debounced so typing in the search box doesn't fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => void refresh(), 250);
    return () => clearTimeout(timer);
  }, [refresh]);

  const totals = summary?.totals;
  const loading = cases === null;
  const blockerChartData = useMemo(
    () =>
      (summary?.byBlocker ?? []).map((row) => ({
        blocker: row.blockerCode,
        cases: row.cases,
      })),
    [summary]
  );

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold text-foreground">Coaching queue</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Offer blockers and friction points your reps hit on calls, with the coaching you have recorded against each
            one.
          </p>
        </div>
        <Button onClick={() => setDialogOpen(true)}>
          <CirclePlus className="mr-2 h-4 w-4" />
          New case
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertTitle>Could not load coaching data</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Headline summary above the detail list. */}
      <section className="space-y-2">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiTile label="Open" value={totals?.openCases ?? 0} context="cases · awaiting coaching" loading={!summary} />
          <KpiTile
            label="In coaching"
            value={totals?.inCoachingCases ?? 0}
            context="cases · in progress"
            loading={!summary}
          />
          <KpiTile
            label="Overdue follow-ups"
            value={totals?.overdueFollowUps ?? 0}
            context="cases · past their follow-up date"
            tone={totals && totals.overdueFollowUps > 0 ? 'destructive' : 'neutral'}
            loading={!summary}
          />
          <KpiTile
            label="Resolved"
            value={totals?.resolvedLast30Days ?? 0}
            context="cases · last 30 days"
            tone="neutral"
            loading={!summary}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Source: your coaching records in Lakebase (<code>sales_coaching</code>)
          {summary ? ` · as of ${formatTime(summary.asOf)}` : ' · loading…'} · {totals?.createdLast7Days ?? 0} created
          in the last 7 days · {totals?.openActions ?? 0} open action items
        </p>
      </section>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Active cases by blocker code</CardTitle>
            <CardDescription>
              Open and in-coaching cases only. Codes follow the pipeline taxonomy (4A–4F).
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!summary ? (
              <Skeleton className="h-[260px] w-full" />
            ) : blockerChartData.length === 0 ? (
              <Empty>
                <EmptyHeader>
                  <EmptyTitle>Nothing active</EmptyTitle>
                  <EmptyDescription>Create a case from a Genie finding to start tracking coaching.</EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <BarChart
                data={blockerChartData}
                xKey="blocker"
                yKey="cases"
                orientation="horizontal"
                colorPalette="categorical"
                height={260}
                showLegend={false}
                ariaLabel="Active coaching cases by blocker code"
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Load by salesperson</CardTitle>
            <CardDescription>Active cases, real blockers, and average coaching score.</CardDescription>
          </CardHeader>
          <CardContent>
            {!summary ? (
              <div className="space-y-2">
                {Array.from({ length: 4 }, (_, i) => (
                  <Skeleton key={`load-skeleton-${i}`} className="h-6 w-full" />
                ))}
              </div>
            ) : summary.bySalesperson.length === 0 ? (
              <Empty>
                <EmptyHeader>
                  <EmptyTitle>No active roster</EmptyTitle>
                  <EmptyDescription>Add salespeople on the Team page.</EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <ul className="space-y-2 text-sm">
                {summary.bySalesperson.map((row) => (
                  <li
                    key={row.salespersonId}
                    className="flex items-center justify-between gap-2 border-b pb-2 last:border-0 last:pb-0"
                  >
                    <button
                      type="button"
                      className="truncate text-left hover:underline"
                      onClick={() => setSalespersonId(String(row.salespersonId))}
                    >
                      {row.fullName}
                    </button>
                    <span className="shrink-0 tabular-nums text-muted-foreground">
                      {row.activeCases} active · {row.blockerCases} blockers ·{' '}
                      {row.avgCoachingRating === null ? 'no score' : `${row.avgCoachingRating}/5`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Cases</CardTitle>
          <CardDescription>Sorted by status, then priority, then follow-up date.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-2">
              <Label htmlFor="filter-search">Search</Label>
              <Input
                id="filter-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Title, opportunity, evidence, rep"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="filter-status">Status</Label>
              <Select value={status} onValueChange={setStatus}>
                <SelectTrigger id="filter-status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All statuses</SelectItem>
                  <SelectItem value="open">Open</SelectItem>
                  <SelectItem value="in_coaching">In coaching</SelectItem>
                  <SelectItem value="resolved">Resolved</SelectItem>
                  <SelectItem value="dismissed">Dismissed</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="filter-rep">Salesperson</Label>
              <Select value={salespersonId} onValueChange={setSalespersonId}>
                <SelectTrigger id="filter-rep">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Everyone</SelectItem>
                  {salespeople.map((person) => (
                    <SelectItem key={person.id} value={String(person.id)}>
                      {person.fullName}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end gap-2 pb-2">
              <Switch id="filter-blockers" checked={blockersOnly} onCheckedChange={setBlockersOnly} />
              <Label htmlFor="filter-blockers" className="text-sm">
                Real blockers only
              </Label>
            </div>
          </div>

          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={`row-skeleton-${i}`} className="h-10 w-full" />
              ))}
            </div>
          ) : cases.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyTitle>No cases match</EmptyTitle>
                <EmptyDescription>
                  {blockersOnly || search || status !== ALL || salespersonId !== ALL
                    ? 'Clear the filters, or ask Genie a question and create a case from the answer.'
                    : 'Ask the offer-blocker agent a question, then create a coaching case from the answer.'}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Case</TableHead>
                    <TableHead>Salesperson</TableHead>
                    <TableHead>Blocker</TableHead>
                    <TableHead>Impact</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Priority</TableHead>
                    <TableHead>Follow-up</TableHead>
                    <TableHead className="text-right">Notes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {cases.map((item) => (
                    <TableRow
                      key={item.id}
                      className="cursor-pointer"
                      onClick={() => void navigate(`/cases/${item.id}`)}
                    >
                      <TableCell className="max-w-[260px]">
                        <span className="block truncate font-medium">{item.title}</span>
                        {item.opportunityId && (
                          <span className="block truncate text-xs text-muted-foreground">{item.opportunityId}</span>
                        )}
                      </TableCell>
                      <TableCell>{item.salespersonName ?? 'Unassigned'}</TableCell>
                      <TableCell>
                        {item.blockerCode ? `${item.blockerCode} · ${item.blockerName ?? ''}` : '—'}
                      </TableCell>
                      <TableCell>
                        <DispositionBadge disposition={item.disposition} />
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={item.status} />
                      </TableCell>
                      <TableCell>
                        <PriorityBadge priority={item.priority} />
                      </TableCell>
                      <TableCell>
                        {isOverdue(item.followUpOn, item.status) ? <OverdueBadge /> : formatDate(item.followUpOn)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {item.feedbackCount} · {item.openActions} open
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <CaseFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        salespeople={salespeople}
        source="manual"
        onCreated={(created) => void navigate(`/cases/${created.id}`)}
      />
    </div>
  );
}
