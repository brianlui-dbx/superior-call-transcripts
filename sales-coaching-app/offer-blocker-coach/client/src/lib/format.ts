/** Display helpers shared across the coaching screens. */

import type { CasePriority, CaseStatus } from './api';

export const STATUS_LABELS: Record<CaseStatus, string> = {
  open: 'Open',
  in_coaching: 'In coaching',
  resolved: 'Resolved',
  dismissed: 'Dismissed',
};

export const PRIORITY_LABELS: Record<CasePriority, string> = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
};

/** How the upstream pipeline grades a finding's impact on the deal. */
export const DISPOSITION_LABELS: Record<string, string> = {
  hard_blocker: 'Hard blocker',
  friction: 'Friction',
  mention_only: 'Mention only',
  resolved: 'Resolved on call',
  latent: 'Latent (hypothesis)',
  insufficient_evidence: 'Insufficient evidence',
};

/** Only hard blockers and friction count as real blockers upstream. */
export function isBlockingDisposition(disposition: string | null): boolean {
  return disposition === 'hard_blocker' || disposition === 'friction';
}

export function dispositionLabel(disposition: string | null): string {
  if (!disposition) return 'Not classified';
  return DISPOSITION_LABELS[disposition] ?? disposition;
}

/**
 * Formats a date for display.
 *
 * DATE columns arrive as `YYYY-MM-DD` with no timezone. Parsing them as UTC and
 * then formatting in the viewer's local zone shifts the calendar day backwards
 * anywhere west of UTC, so a follow-up set to the 14th renders as the 13th.
 * Date-only values are therefore formatted in UTC to keep the day exact;
 * timestamps, which do carry a zone, stay local.
 */
export function formatDate(value: string | null): string {
  if (!value) return '—';
  const isDateOnly = value.length === 10;
  const date = new Date(isDateOnly ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    ...(isDateOnly ? { timeZone: 'UTC' } : {}),
  });
}

export function formatDateTime(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

/**
 * True when a follow-up date has passed and the case is still active.
 *
 * Compared against the viewer's local calendar day (the same basis as the date
 * picker's `min`), so "overdue" matches what the manager sees on their own
 * calendar rather than UTC's.
 */
export function isOverdue(followUpOn: string | null, status: CaseStatus): boolean {
  if (!followUpOn) return false;
  if (status !== 'open' && status !== 'in_coaching') return false;
  return followUpOn < todayISO();
}

/** `today` in the local timezone, formatted for a date input's `min`. */
export function todayISO(): string {
  const now = new Date();
  const offsetMs = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 10);
}
