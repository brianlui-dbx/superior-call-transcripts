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
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  GenieChatInput,
  GenieChatMessageList,
  GenieQueryVisualization,
  Separator,
  Spinner,
  useGenieChat,
} from '@databricks/appkit-ui/react';
import { useEffect, useMemo, useState } from 'react';
import { CirclePlus, RotateCcw, ShieldCheck } from 'lucide-react';
import { api, type CaseDetail, type Salesperson } from '@/lib/api';
import { useIdentity } from '@/lib/useIdentity';
import { COACHING_PROMPTS } from '@/lib/taxonomy';
import { CaseFormDialog, type CasePrefill } from '@/components/CaseFormDialog';

/** Must match the alias registered with the genie plugin in server/server.ts. */
const GENIE_ALIAS = 'offerBlockers';

export function GeniePage() {
  const { messages, status, error, sendMessage, reset, conversationId } = useGenieChat({
    alias: GENIE_ALIAS,
  });
  const identity = useIdentity();
  const [salespeople, setSalespeople] = useState<Salesperson[]>([]);
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [createdCase, setCreatedCase] = useState<CaseDetail | null>(null);

  useEffect(() => {
    api
      .listSalespeople()
      .then(setSalespeople)
      .catch((err: unknown) => setRosterError(err instanceof Error ? err.message : 'Failed to load the roster'));
  }, []);

  const lastAnswer = useMemo(
    () => [...messages].reverse().find((message) => message.role === 'assistant') ?? null,
    [messages]
  );
  const lastQuestion = useMemo(
    () => [...messages].reverse().find((message) => message.role === 'user') ?? null,
    [messages]
  );

  /** The SQL Genie generated for the most recent answer. */
  const generatedQuery = useMemo(() => {
    for (const attachment of lastAnswer?.attachments ?? []) {
      if (attachment.query) return attachment.query;
    }
    return null;
  }, [lastAnswer]);

  /** The first tabular result attached to the most recent answer, if any. */
  const resultData = useMemo(() => {
    const first = lastAnswer?.queryResults.values().next();
    return first && !first.done ? first.value : null;
  }, [lastAnswer]);

  const prefill: CasePrefill | undefined = useMemo(() => {
    if (!lastAnswer) return undefined;
    const question = lastQuestion?.content ?? '';
    return {
      title: question.length > 90 ? `${question.slice(0, 87)}…` : question || 'Coaching case from Genie',
      evidence: lastAnswer.content,
      genieQuestion: question || undefined,
      genieAnswer: lastAnswer.content,
      genieSql: generatedQuery?.query ?? undefined,
      genieConversationId: conversationId ?? undefined,
    };
  }, [lastAnswer, lastQuestion, generatedQuery, conversationId]);

  const isStreaming = status === 'streaming';
  const hasAnswer = Boolean(lastAnswer && lastAnswer.content);

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold text-foreground">Ask the offer-blocker agent</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Natural-language questions over the curated{' '}
            <span className="font-medium text-foreground">Offer Blocker Analytics</span> Genie agent — blocker findings,
            call tone, quoted rates and follow-up emails.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="secondary">{identity?.email ?? 'Signed in'}</Badge>
          <Button variant="outline" size="sm" onClick={reset} disabled={messages.length === 0}>
            <RotateCcw className="mr-2 h-4 w-4" />
            New conversation
          </Button>
        </div>
      </div>

      {/* Governance: states the real execution identity on each side of the app. */}
      <Alert>
        <ShieldCheck className="h-4 w-4" />
        <AlertTitle>How this runs</AlertTitle>
        <AlertDescription>
          Genie queries execute <strong>on your behalf</strong> — the app declares the <code>dashboards.genie</code>{' '}
          user scope, so you only ever see data your own Unity Catalog permissions allow. Coaching notes you save are
          written to Lakebase by the app&apos;s service principal and attributed to{' '}
          {identity?.email ?? 'your signed-in account'}.
        </AlertDescription>
      </Alert>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Card className="flex min-h-[560px] flex-col">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Conversation</CardTitle>
            <CardDescription>Start from a coaching question or ask your own.</CardDescription>
          </CardHeader>
          <CardContent className="flex min-h-0 flex-1 flex-col gap-3">
            <div className="flex flex-wrap gap-2">
              {COACHING_PROMPTS.map((prompt) => (
                <Button
                  key={prompt.label}
                  variant="outline"
                  size="sm"
                  disabled={isStreaming}
                  onClick={() => sendMessage(prompt.question)}
                >
                  {prompt.label}
                </Button>
              ))}
            </div>

            <Separator />

            <div className="min-h-0 flex-1">
              {messages.length === 0 && status === 'idle' ? (
                <Empty>
                  <EmptyHeader>
                    <EmptyTitle>No questions yet</EmptyTitle>
                    <EmptyDescription>
                      Pick a coaching question above, or ask something like &ldquo;which reps have the most hard
                      blockers?&rdquo;
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                <GenieChatMessageList messages={messages} status={status} className="h-full" />
              )}
            </div>

            {/* Live status, never a frozen spinner. */}
            {isStreaming && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Spinner className="h-4 w-4" />
                Genie is analysing your data…
              </p>
            )}
            {status === 'loading-history' && (
              <p className="text-sm text-muted-foreground">Restoring this conversation…</p>
            )}
            {status === 'error' && (
              <Alert variant="destructive">
                <AlertTitle>Genie could not answer that</AlertTitle>
                <AlertDescription>{error ?? 'Rephrase the question, or retry in a moment.'}</AlertDescription>
              </Alert>
            )}

            <GenieChatInput
              onSend={sendMessage}
              disabled={isStreaming}
              placeholder="Ask about blockers, tone, quoted rates or a specific opportunity…"
            />

            {/* Per-answer disclaimer. */}
            <p className="text-xs text-muted-foreground">
              AI-generated from your lakehouse data via Genie — review the generated SQL below before acting on an
              answer or coaching a rep on it.
            </p>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Generated SQL</CardTitle>
              <CardDescription>{generatedQuery?.title ?? 'How the latest answer was computed'}</CardDescription>
            </CardHeader>
            <CardContent>
              {generatedQuery?.query ? (
                <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs leading-relaxed">
                  {generatedQuery.query}
                </pre>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {isStreaming
                    ? 'Waiting for Genie to generate the query…'
                    : 'Ask a question to see the exact SQL Genie ran.'}
                </p>
              )}
              {generatedQuery?.description && (
                <p className="mt-2 text-xs text-muted-foreground">{generatedQuery.description}</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Coach on this finding</CardTitle>
              <CardDescription>Turn the latest answer into a tracked coaching case in Lakebase.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {rosterError && (
                <Alert variant="destructive">
                  <AlertDescription>{rosterError}</AlertDescription>
                </Alert>
              )}
              <Button className="w-full" disabled={!hasAnswer || isStreaming} onClick={() => setDialogOpen(true)}>
                <CirclePlus className="mr-2 h-4 w-4" />
                Create coaching case
              </Button>
              {!hasAnswer && (
                <p className="text-xs text-muted-foreground">Available once Genie has returned an answer.</p>
              )}
              {createdCase && (
                <Alert>
                  <AlertDescription>
                    Saved case #{createdCase.id} —{' '}
                    <a
                      className="font-medium text-primary underline underline-offset-4"
                      href={`/cases/${createdCase.id}`}
                    >
                      open it in the coaching queue
                    </a>
                    .
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>

          {resultData && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Result</CardTitle>
                <CardDescription>Returned by the query above.</CardDescription>
              </CardHeader>
              <CardContent>
                <GenieQueryVisualization data={resultData} />
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <CaseFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        salespeople={salespeople}
        prefill={prefill}
        source="genie"
        onCreated={setCreatedCase}
      />
    </div>
  );
}
