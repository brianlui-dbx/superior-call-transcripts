import { Badge } from '@databricks/appkit-ui/react';
import type { CasePriority, CaseStatus } from '@/lib/api';
import { PRIORITY_LABELS, STATUS_LABELS, dispositionLabel } from '@/lib/format';

/** Status reads as progress, so only terminal-negative states take an accent. */
export function StatusBadge({ status }: { status: CaseStatus }) {
  const variant = status === 'resolved' ? 'secondary' : status === 'dismissed' ? 'outline' : 'default';
  return <Badge variant={variant}>{STATUS_LABELS[status]}</Badge>;
}

/** Priority is a severity scale: high is destructive, medium cautionary. */
export function PriorityBadge({ priority }: { priority: CasePriority }) {
  if (priority === 'high') return <Badge variant="destructive">{PRIORITY_LABELS.high}</Badge>;
  if (priority === 'medium') {
    return (
      <Badge variant="outline" className="border-warning text-warning">
        {PRIORITY_LABELS.medium}
      </Badge>
    );
  }
  return <Badge variant="outline">{PRIORITY_LABELS.low}</Badge>;
}

/**
 * Disposition comes from the pipeline, not the manager. Hard blocker and
 * friction are the only values that count as real blockers upstream.
 */
export function DispositionBadge({ disposition }: { disposition: string | null }) {
  const label = dispositionLabel(disposition);
  if (disposition === 'hard_blocker') return <Badge variant="destructive">{label}</Badge>;
  if (disposition === 'friction') {
    return (
      <Badge variant="outline" className="border-warning text-warning">
        {label}
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-muted-foreground">
      {label}
    </Badge>
  );
}

export function OverdueBadge() {
  return <Badge variant="destructive">Follow-up overdue</Badge>;
}
