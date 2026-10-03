import { describe, expect, it } from 'vitest';
import {
  CaseListQuery,
  CreateActionBody,
  CreateCaseBody,
  CreateFeedbackBody,
  UpdateCaseBody,
  UpdateSalespersonBody,
} from '../domain';
import { buildUpdate, parseId } from '../db';

describe('CreateCaseBody', () => {
  it('requires a title', () => {
    const result = CreateCaseBody.safeParse({ title: '   ' });
    expect(result.success).toBe(false);
  });

  it('applies coaching defaults and normalises blank optional text to null', () => {
    const result = CreateCaseBody.parse({ title: 'Coach on rental fee', opportunityId: '' });
    expect(result.status).toBe('open');
    expect(result.priority).toBe('medium');
    expect(result.source).toBe('manual');
    expect(result.opportunityId).toBeNull();
    expect(result.salespersonId).toBeNull();
  });

  it('rejects a follow-up date that is not an ISO day', () => {
    expect(CreateCaseBody.safeParse({ title: 'x', followUpOn: '12/31/2026' }).success).toBe(false);
    expect(CreateCaseBody.parse({ title: 'x', followUpOn: '2026-12-31' }).followUpOn).toBe('2026-12-31');
  });

  it('rejects an unknown disposition-bearing status', () => {
    expect(CreateCaseBody.safeParse({ title: 'x', status: 'archived' }).success).toBe(false);
  });
});

describe('UpdateCaseBody', () => {
  it('rejects an empty patch', () => {
    expect(UpdateCaseBody.safeParse({}).success).toBe(false);
  });

  it('allows clearing the follow-up date and unassigning the rep', () => {
    const result = UpdateCaseBody.parse({ followUpOn: null, salespersonId: null });
    expect(result.followUpOn).toBeNull();
    expect(result.salespersonId).toBeNull();
  });

  it('treats an empty date string as a clear', () => {
    expect(UpdateCaseBody.parse({ followUpOn: '' }).followUpOn).toBeNull();
  });

  /*
   * Regression guard: optional fields must stay `undefined` when the caller
   * omits them. If they parsed to `null` instead, buildUpdate would emit
   * `follow_up_on = NULL, evidence = NULL` on a status-only patch and silently
   * destroy data the manager never touched.
   */
  it('does not fabricate nulls for fields the caller omitted', () => {
    const result = UpdateCaseBody.parse({ status: 'resolved' });
    expect(result.followUpOn).toBeUndefined();
    expect(result.evidence).toBeUndefined();
    expect(result.salespersonId).toBeUndefined();

    const { clause, values } = buildUpdate({
      salesperson_id: result.salespersonId,
      title: result.title,
      status: result.status,
      priority: result.priority,
      follow_up_on: result.followUpOn,
      evidence: result.evidence,
    });
    expect(clause).toBe('status = $1');
    expect(values).toEqual(['resolved']);
  });
});

describe('CreateFeedbackBody', () => {
  it('requires a note', () => {
    expect(CreateFeedbackBody.safeParse({ note: '' }).success).toBe(false);
  });

  it('keeps ratings inside 1-5', () => {
    expect(CreateFeedbackBody.safeParse({ note: 'ok', coachingRating: 0 }).success).toBe(false);
    expect(CreateFeedbackBody.safeParse({ note: 'ok', coachingRating: 6 }).success).toBe(false);
    expect(CreateFeedbackBody.parse({ note: 'ok', coachingRating: 4 }).coachingRating).toBe(4);
  });

  it('defaults both verdicts to null when omitted', () => {
    const result = CreateFeedbackBody.parse({ note: 'Discussed fee framing' });
    expect(result.coachingRating).toBeNull();
    expect(result.findingAccurate).toBeNull();
  });
});

describe('CreateActionBody', () => {
  it('requires a description', () => {
    expect(CreateActionBody.safeParse({ description: ' ' }).success).toBe(false);
  });

  it('trims the description and keeps a valid due date', () => {
    const result = CreateActionBody.parse({ description: '  Re-quote  ', dueOn: '2026-11-01' });
    expect(result.description).toBe('Re-quote');
    expect(result.dueOn).toBe('2026-11-01');
  });
});

describe('CaseListQuery', () => {
  it('coerces the salesperson id and treats blockersOnly as a flag', () => {
    const result = CaseListQuery.parse({ salespersonId: '7', blockersOnly: 'true' });
    expect(result.salespersonId).toBe(7);
    expect(result.blockersOnly).toBe(true);
  });

  it('defaults blockersOnly to false when absent', () => {
    expect(CaseListQuery.parse({}).blockersOnly).toBe(false);
  });

  it('rejects an unknown status', () => {
    expect(CaseListQuery.safeParse({ status: 'nope' }).success).toBe(false);
  });
});

describe('UpdateSalespersonBody', () => {
  it('rejects an empty patch but allows a lone active toggle', () => {
    expect(UpdateSalespersonBody.safeParse({}).success).toBe(false);
    const result = UpdateSalespersonBody.parse({ active: false });
    expect(result.active).toBe(false);
    expect(result.fullName).toBeUndefined();
    expect(result.teamName).toBeUndefined();
  });
});

describe('buildUpdate', () => {
  it('skips undefined columns and numbers the placeholders in order', () => {
    const { clause, values } = buildUpdate({ status: 'open', priority: undefined, title: 'x' });
    expect(clause).toBe('status = $1, title = $2');
    expect(values).toEqual(['open', 'x']);
  });

  it('keeps explicit nulls so a field can be cleared', () => {
    const { clause, values } = buildUpdate({ follow_up_on: null });
    expect(clause).toBe('follow_up_on = $1');
    expect(values).toEqual([null]);
  });

  it('honours an offset so it can follow other bound parameters', () => {
    const { clause } = buildUpdate({ done: true }, 3);
    expect(clause).toBe('done = $3');
  });

  it('returns an empty clause when nothing was supplied', () => {
    expect(buildUpdate({ a: undefined }).clause).toBe('');
  });
});

describe('parseId', () => {
  it('accepts positive integers only', () => {
    expect(parseId('42')).toBe(42);
    expect(parseId('0')).toBeNull();
    expect(parseId('-3')).toBeNull();
    expect(parseId('1.5')).toBeNull();
    expect(parseId('abc')).toBeNull();
    expect(parseId(undefined)).toBeNull();
  });
});
