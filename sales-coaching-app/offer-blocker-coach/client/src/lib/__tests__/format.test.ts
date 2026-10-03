import { describe, expect, it } from 'vitest';
import { formatDate, formatDateTime, isOverdue, todayISO } from '../format';

describe('formatDate', () => {
  /*
   * Regression guard: a DATE column has no timezone. Formatting it in the local
   * zone after parsing as UTC moved the day back one anywhere west of UTC, so a
   * follow-up saved as the 14th displayed as the 13th.
   */
  it('keeps a date-only value on its exact calendar day', () => {
    const formatted = formatDate('2026-11-14');
    expect(formatted).toContain('14');
    expect(formatted).not.toContain('13');
  });

  it('handles the first of a month without slipping into the previous one', () => {
    const formatted = formatDate('2026-01-01');
    expect(formatted).toContain('1');
    expect(formatted).toContain('2026');
    expect(formatted).not.toContain('2025');
  });

  it('renders a placeholder for no date and echoes an unparseable one', () => {
    expect(formatDate(null)).toBe('—');
    expect(formatDate('not-a-date')).toBe('not-a-date');
  });
});

describe('formatDateTime', () => {
  it('formats an ISO timestamp and falls back for junk', () => {
    expect(formatDateTime('2026-10-02T12:00:00Z')).toMatch(/2026/);
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime('nope')).toBe('nope');
  });
});

describe('isOverdue', () => {
  it('flags a past follow-up on an active case', () => {
    expect(isOverdue('2020-01-01', 'open')).toBe(true);
    expect(isOverdue('2020-01-01', 'in_coaching')).toBe(true);
  });

  it('ignores closed cases and future or missing dates', () => {
    expect(isOverdue('2020-01-01', 'resolved')).toBe(false);
    expect(isOverdue('2020-01-01', 'dismissed')).toBe(false);
    expect(isOverdue('2099-01-01', 'open')).toBe(false);
    expect(isOverdue(null, 'open')).toBe(false);
  });

  it('does not treat today as overdue', () => {
    expect(isOverdue(todayISO(), 'open')).toBe(false);
  });
});
