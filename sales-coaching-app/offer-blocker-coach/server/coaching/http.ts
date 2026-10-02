/** Small request/response helpers shared by the coaching route modules. */

import type { Response } from 'express';
import type { z } from 'zod';

/**
 * Validates `data` against `schema`. On failure it writes a 400 with the first
 * validation message and returns `null`, so handlers can `if (!input) return;`.
 */
export function parseOr400<S extends z.ZodType>(schema: S, data: unknown, res: Response): z.infer<S> | null {
  const result = schema.safeParse(data);
  if (result.success) return result.data;
  res.status(400).json({ error: result.error.issues[0]?.message ?? 'invalid request' });
  return null;
}

/** Logs the cause server-side and returns a generic message to the caller. */
export function fail(res: Response, message: string, err: unknown): void {
  console.error(`[coaching] ${message}`, err);
  res.status(500).json({ error: message });
}

/** TIMESTAMPTZ columns arrive as `Date`; the API always speaks ISO strings. */
export function iso(value: Date | string | null): string | null {
  if (value === null) return null;
  return value instanceof Date ? value.toISOString() : value;
}
