import {
  Alert,
  AlertDescription,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from '@databricks/appkit-ui/react';
import { useEffect, useState } from 'react';
import { api, type CaseDetail, type CasePriority, type NewCase, type Salesperson } from '@/lib/api';
import { todayISO } from '@/lib/format';
import { BLOCKER_CODES, DISPOSITIONS, blockerName } from '@/lib/taxonomy';

const UNASSIGNED = 'unassigned';
const NONE = 'none';

export interface CasePrefill {
  title?: string;
  opportunityId?: string;
  blockerCode?: string;
  disposition?: string;
  evidence?: string;
  region?: string;
  salesforceStage?: string;
  genieQuestion?: string;
  genieAnswer?: string;
  genieSql?: string;
  genieConversationId?: string;
}

/**
 * Creates a coaching case. When opened from an answer, the Genie question,
 * answer text, generated SQL, and conversation id ride along as provenance so
 * the coaching record stays traceable to the analysis that prompted it.
 */
export function CaseFormDialog({
  open,
  onOpenChange,
  salespeople,
  prefill,
  source,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  salespeople: Salesperson[];
  prefill?: CasePrefill;
  source: 'genie' | 'manual';
  onCreated: (created: CaseDetail) => void;
}) {
  const [salespersonId, setSalespersonId] = useState(UNASSIGNED);
  const [title, setTitle] = useState('');
  const [opportunityId, setOpportunityId] = useState('');
  const [blockerCode, setBlockerCode] = useState(NONE);
  const [disposition, setDisposition] = useState(NONE);
  const [priority, setPriority] = useState<CasePriority>('medium');
  const [followUpOn, setFollowUpOn] = useState('');
  const [evidence, setEvidence] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Re-seed from the prefill each time the dialog opens.
  useEffect(() => {
    if (!open) return;
    setTitle(prefill?.title ?? '');
    setOpportunityId(prefill?.opportunityId ?? '');
    setBlockerCode(prefill?.blockerCode ?? NONE);
    setDisposition(prefill?.disposition ?? NONE);
    setEvidence(prefill?.evidence ?? '');
    setSalespersonId(UNASSIGNED);
    setPriority(prefill?.disposition === 'hard_blocker' ? 'high' : 'medium');
    setFollowUpOn('');
    setError(null);
  }, [open, prefill]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!title.trim()) {
      setError('Give the case a short title so it is recognisable in the queue.');
      return;
    }

    const payload: NewCase = {
      salespersonId: salespersonId === UNASSIGNED ? null : Number(salespersonId),
      title: title.trim(),
      opportunityId: opportunityId.trim() || null,
      blockerCode: blockerCode === NONE ? null : blockerCode,
      blockerName: blockerCode === NONE ? null : blockerName(blockerCode),
      disposition: disposition === NONE ? null : disposition,
      evidence: evidence.trim() || null,
      region: prefill?.region ?? null,
      salesforceStage: prefill?.salesforceStage ?? null,
      priority,
      followUpOn: followUpOn || null,
      source,
      genieQuestion: prefill?.genieQuestion ?? null,
      genieAnswer: prefill?.genieAnswer ?? null,
      genieSql: prefill?.genieSql ?? null,
      genieConversationId: prefill?.genieConversationId ?? null,
    };

    setSaving(true);
    setError(null);
    try {
      const created = await api.createCase(payload);
      onCreated(created);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create the coaching case');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>New coaching case</DialogTitle>
          <DialogDescription>
            {source === 'genie'
              ? 'The Genie question, answer and generated SQL are attached to this case as provenance.'
              : 'Record a blocker you want to coach, then add notes and agreed actions.'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={(event) => void submit(event)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="case-title">Title</Label>
            <Input
              id="case-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Coach on rental fee objection handling"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="case-salesperson">Salesperson</Label>
              <Select value={salespersonId} onValueChange={setSalespersonId}>
                <SelectTrigger id="case-salesperson">
                  <SelectValue placeholder="Unassigned" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={UNASSIGNED}>Unassigned</SelectItem>
                  {salespeople.map((person) => (
                    <SelectItem key={person.id} value={String(person.id)}>
                      {person.fullName}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="case-opportunity">Opportunity ID</Label>
              <Input
                id="case-opportunity"
                value={opportunityId}
                onChange={(e) => setOpportunityId(e.target.value)}
                placeholder="e.g. 0065f00000ABCDE"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="case-blocker">Blocker code</Label>
              <Select value={blockerCode} onValueChange={setBlockerCode}>
                <SelectTrigger id="case-blocker">
                  <SelectValue placeholder="Not coded" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>Not coded</SelectItem>
                  {BLOCKER_CODES.map((entry) => (
                    <SelectItem key={entry.code} value={entry.code}>
                      {entry.code} — {entry.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="case-disposition">Disposition</Label>
              <Select value={disposition} onValueChange={setDisposition}>
                <SelectTrigger id="case-disposition">
                  <SelectValue placeholder="Not classified" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>Not classified</SelectItem>
                  {DISPOSITIONS.map((entry) => (
                    <SelectItem key={entry.value} value={entry.value}>
                      {entry.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="case-priority">Coaching priority</Label>
              <Select value={priority} onValueChange={(value) => setPriority(value as CasePriority)}>
                <SelectTrigger id="case-priority">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="low">Low</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="case-followup">Follow up on</Label>
              <Input
                id="case-followup"
                type="date"
                min={todayISO()}
                value={followUpOn}
                onChange={(e) => setFollowUpOn(e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="case-evidence">Evidence from the call</Label>
            <Textarea
              id="case-evidence"
              value={evidence}
              onChange={(e) => setEvidence(e.target.value)}
              rows={4}
              placeholder="Paste the customer quote or the finding's evidence text"
            />
          </div>

          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Creating…' : 'Create case'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
