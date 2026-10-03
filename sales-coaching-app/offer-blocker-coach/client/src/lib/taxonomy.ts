/**
 * The offer-blocker taxonomy this repo's pipeline produces, mirrored for the
 * coaching form, plus the curated questions a manager most often asks Genie.
 */

export const BLOCKER_CODES: { code: string; name: string; summary: string }[] = [
  { code: '4A', name: 'Rate competitiveness', summary: 'Quoted rate, competitor comparison, price-match' },
  { code: '4B', name: 'Ancillary fees', summary: 'Delivery, rental, installation, inspection, admin fees' },
  { code: '4C', name: 'Commercial model', summary: 'Pre-buy, tank ownership, pricing mechanism, commitment' },
  { code: '4D', name: 'Contract mechanics', summary: 'Auto-renewal, exit terms, billing, transaction process' },
  { code: '4E', name: 'Availability / serviceability', summary: 'Coverage, product, equipment, site, timeline gap' },
  { code: '4F', name: 'Promotion eligibility', summary: 'Referral, threshold, ownership, timing, policy limits' },
];

export const DISPOSITIONS = [
  { value: 'hard_blocker', label: 'Hard blocker — deal-killer' },
  { value: 'friction', label: 'Friction — slowed the deal' },
  { value: 'mention_only', label: 'Mention only — no effect' },
  { value: 'resolved', label: 'Resolved on the call' },
  { value: 'latent', label: 'Latent — hypothesis only' },
  { value: 'insufficient_evidence', label: 'Insufficient evidence' },
];

/**
 * Starter questions written against the agent's curated instructions, so a
 * manager gets useful coaching evidence without learning the schema.
 */
export const COACHING_PROMPTS: { label: string; question: string }[] = [
  {
    label: 'Blockers to coach now',
    question:
      'List opportunities where the disposition is hard_blocker or friction. Show Opp ID, Code Name, Qualifier, Disposition, Confidence and Evidence.',
  },
  {
    label: 'Most common blocker codes',
    question: 'What are the most common blocker codes across all opportunities?',
  },
  {
    label: 'Negative tone + hard blocker',
    question: 'Which opportunities have both a hard blocker and negative call tone?',
  },
  {
    label: 'Closed-lost post-mortem',
    question: 'For closed lost opportunities, what were the primary blockers and how did call sentiment correlate?',
  },
  {
    label: 'Fee objections (4B)',
    question: 'Show all 4B ancillary fee findings with their qualifier, disposition and evidence quote.',
  },
  {
    label: 'Rate pressure (4A)',
    question: 'What is the final quoted rate amount for opportunities that had rate competitiveness issues (4A)?',
  },
];

export function blockerName(code: string | null): string | null {
  if (!code) return null;
  return BLOCKER_CODES.find((entry) => entry.code === code)?.name ?? null;
}
