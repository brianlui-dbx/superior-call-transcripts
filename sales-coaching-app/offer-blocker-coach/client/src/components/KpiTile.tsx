import { Card, CardContent, Skeleton } from '@databricks/appkit-ui/react';

/**
 * AppKit ships no KPI card, so this composes one from primitives: a value, the
 * unit and period it covers, and an optional accent when the number demands
 * action. Provenance is stated once per group by the caller.
 */
export function KpiTile({
  label,
  value,
  context,
  tone = 'neutral',
  loading = false,
}: {
  label: string;
  value: number | string;
  /** Unit + period, e.g. "cases · last 30 days". */
  context: string;
  tone?: 'neutral' | 'warning' | 'destructive';
  loading?: boolean;
}) {
  const toneClass =
    tone === 'destructive' ? 'text-destructive' : tone === 'warning' ? 'text-warning' : 'text-foreground';

  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
        {loading ? (
          <Skeleton className="mt-2 h-8 w-16" />
        ) : (
          <p className={`mt-1 text-3xl font-semibold tabular-nums ${toneClass}`}>{value}</p>
        )}
        <p className="mt-1 text-xs text-muted-foreground">{context}</p>
      </CardContent>
    </Card>
  );
}
