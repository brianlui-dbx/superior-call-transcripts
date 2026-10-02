/**
 * Domain contract for the sales-manager coaching workflow.
 *
 * Genie ("Offer Blocker Analytics") supplies the analytical finding; everything a
 * manager *decides* about that finding — assignment, status, coaching notes,
 * agreed actions — is operational state that lives in Lakebase.
 */

import { z } from 'zod';

/** Schema the app's service principal owns in Lakebase. */
export const SCHEMA = 'sales_coaching';

export const CASE_STATUSES = ['open', 'in_coaching', 'resolved', 'dismissed'] as const;
export const CASE_PRIORITIES = ['high', 'medium', 'low'] as const;
export const CASE_SOURCES = ['genie', 'manual'] as const;

export type CaseStatus = (typeof CASE_STATUSES)[number];
export type CasePriority = (typeof CASE_PRIORITIES)[number];

/** Dispositions the upstream pipeline treats as a real blocker rather than context. */
export const BLOCKING_DISPOSITIONS = ['hard_blocker', 'friction'] as const;

const trimmed = (max: number) => z.string().trim().max(max);

/**
 * A required free-text field. The `error` option covers the missing/wrong-type
 * case too, so an omitted field reports "title is required" rather than Zod's
 * default "expected string, received undefined".
 */
const requiredText = (max: number, message: string) => z.string({ error: message }).trim().min(1, message).max(max);
const optionalText = (max: number) =>
  trimmed(max)
    .nullish()
    .transform((v) => (v ? v : null));

/** `YYYY-MM-DD`; kept as a string so a DATE column round-trips without timezone drift. */
const dayString = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'expected YYYY-MM-DD');

const isoDate = dayString.nullish().transform((v) => (v ? v : null));

/*
 * PATCH bodies need a third state that the create-side helpers above cannot
 * express. There, an absent field means "store NULL". In an update, an absent
 * field must mean "leave this column alone" — only an explicit `null` (or empty
 * string) may clear it. `.optional()` is applied outermost so a missing key
 * short-circuits to `undefined` instead of flowing through the transform, which
 * is what keeps `buildUpdate` from overwriting columns the caller never sent.
 */
const patchText = (max: number) =>
  z
    .union([trimmed(max), z.null()])
    .transform((v) => (v ? v : null))
    .optional();

const patchDate = z
  .union([dayString, z.literal(''), z.null()])
  .transform((v) => (v ? v : null))
  .optional();

/** At least one field must actually be present. */
const notEmptyPatch = (body: Record<string, unknown>) => Object.values(body).some((value) => value !== undefined);

export const CreateCaseBody = z.object({
  salespersonId: z
    .number()
    .int()
    .positive()
    .nullish()
    .transform((v) => v ?? null),
  title: requiredText(200, 'title is required'),
  opportunityId: optionalText(80),
  blockerCode: optionalText(16),
  blockerName: optionalText(160),
  disposition: optionalText(40),
  qualifier: optionalText(120),
  confidence: optionalText(40),
  evidence: optionalText(4000),
  region: optionalText(80),
  salesforceStage: optionalText(80),
  priority: z.enum(CASE_PRIORITIES).default('medium'),
  status: z.enum(CASE_STATUSES).default('open'),
  followUpOn: isoDate,
  source: z.enum(CASE_SOURCES).default('manual'),
  genieQuestion: optionalText(2000),
  genieAnswer: optionalText(8000),
  genieSql: optionalText(8000),
  genieConversationId: optionalText(120),
});

export const UpdateCaseBody = z
  .object({
    salespersonId: z.number().int().positive().nullable().optional(),
    title: trimmed(200).min(1).optional(),
    status: z.enum(CASE_STATUSES).optional(),
    priority: z.enum(CASE_PRIORITIES).optional(),
    followUpOn: patchDate,
    evidence: patchText(4000),
  })
  .refine(notEmptyPatch, { message: 'no fields to update' });

export const CreateFeedbackBody = z.object({
  note: requiredText(4000, 'note is required'),
  /** Manager's read on how the rep handled the blocker (1 = poor, 5 = excellent). */
  coachingRating: z
    .number()
    .int()
    .min(1)
    .max(5)
    .nullish()
    .transform((v) => v ?? null),
  /** Manager's verdict on whether the AI finding itself was correct. */
  findingAccurate: z
    .boolean()
    .nullish()
    .transform((v) => v ?? null),
});

export const CreateActionBody = z.object({
  description: requiredText(500, 'description is required'),
  owner: optionalText(160),
  dueOn: isoDate,
});

export const UpdateActionBody = z
  .object({
    description: trimmed(500).min(1).optional(),
    owner: patchText(160),
    dueOn: patchDate,
    done: z.boolean().optional(),
  })
  .refine(notEmptyPatch, { message: 'no fields to update' });

export const CreateSalespersonBody = z.object({
  fullName: requiredText(160, 'fullName is required'),
  agentId: optionalText(64),
  teamName: optionalText(120),
  region: optionalText(80),
  email: optionalText(200),
});

export const UpdateSalespersonBody = z
  .object({
    fullName: trimmed(160).min(1).optional(),
    agentId: patchText(64),
    teamName: patchText(120),
    region: patchText(80),
    email: patchText(200),
    active: z.boolean().optional(),
  })
  .refine(notEmptyPatch, { message: 'no fields to update' });

export const CaseListQuery = z.object({
  status: z.enum(CASE_STATUSES).optional(),
  priority: z.enum(CASE_PRIORITIES).optional(),
  salespersonId: z.coerce.number().int().positive().optional(),
  /** Narrow to findings the pipeline classified as a real blocker. */
  blockersOnly: z
    .enum(['true', 'false'])
    .optional()
    .transform((v) => v === 'true'),
  search: trimmed(120).optional(),
});

export type CreateCaseInput = z.infer<typeof CreateCaseBody>;
export type UpdateCaseInput = z.infer<typeof UpdateCaseBody>;
export type CaseListFilters = z.infer<typeof CaseListQuery>;
