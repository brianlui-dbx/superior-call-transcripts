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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Input,
  Label,
  Skeleton,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@databricks/appkit-ui/react';
import { useCallback, useEffect, useState } from 'react';
import { UserPlus } from 'lucide-react';
import { api, type Salesperson } from '@/lib/api';

/**
 * The roster is the app's own record of who reports to this manager.
 *
 * The transcript source carries an agent id and name, but the pipeline does not
 * currently expose them on the tables Genie reads, so the roster is seeded from
 * the sample batch and then maintained here.
 */
export function TeamPage() {
  const [roster, setRoster] = useState<Salesperson[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Salesperson | null>(null);
  const [addOpen, setAddOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setRoster(await api.listSalespeople(true));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load the roster');
      setRoster([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleActive = async (person: Salesperson, active: boolean) => {
    setBusy(true);
    try {
      await api.updateSalesperson(person.id, { active });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update the roster');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-5xl space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold text-foreground">Team</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            The salespeople you coach. Cases are assigned to people on this list.
          </p>
        </div>
        <Button onClick={() => setAddOpen(true)}>
          <UserPlus className="mr-2 h-4 w-4" />
          Add salesperson
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertTitle>Roster problem</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Roster</CardTitle>
          <CardDescription>
            Seeded from the sample transcript batch on first run, then owned by you. Deactivating someone keeps their
            coaching history but removes them from assignment lists.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {roster === null ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={`roster-skeleton-${i}`} className="h-10 w-full" />
              ))}
            </div>
          ) : roster.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyTitle>No one on the roster</EmptyTitle>
                <EmptyDescription>Add the salespeople you coach to get started.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Team</TableHead>
                    <TableHead>Region</TableHead>
                    <TableHead>Agent ID</TableHead>
                    <TableHead>Active</TableHead>
                    <TableHead className="text-right">Edit</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {roster.map((person) => (
                    <TableRow key={person.id}>
                      <TableCell className="font-medium">
                        {person.fullName}
                        {person.email && <span className="block text-xs text-muted-foreground">{person.email}</span>}
                      </TableCell>
                      <TableCell>{person.teamName ?? '—'}</TableCell>
                      <TableCell>{person.region ?? '—'}</TableCell>
                      <TableCell className="text-muted-foreground">{person.agentId ?? '—'}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Switch
                            id={`active-${person.id}`}
                            checked={person.active}
                            disabled={busy}
                            onCheckedChange={(checked) => void toggleActive(person, checked)}
                          />
                          {!person.active && <Badge variant="outline">Inactive</Badge>}
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => setEditing(person)}>
                          Edit
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <SalespersonDialog
        key={editing ? `edit-${editing.id}` : 'add'}
        person={editing}
        open={addOpen || editing !== null}
        onOpenChange={(open) => {
          if (!open) {
            setAddOpen(false);
            setEditing(null);
          }
        }}
        onSaved={load}
      />
    </div>
  );
}

function SalespersonDialog({
  person,
  open,
  onOpenChange,
  onSaved,
}: {
  person: Salesperson | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => Promise<void>;
}) {
  const [fullName, setFullName] = useState(person?.fullName ?? '');
  const [teamName, setTeamName] = useState(person?.teamName ?? '');
  const [region, setRegion] = useState(person?.region ?? '');
  const [email, setEmail] = useState(person?.email ?? '');
  const [agentId, setAgentId] = useState(person?.agentId ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!fullName.trim()) {
      setError('A name is required.');
      return;
    }
    const payload = {
      fullName: fullName.trim(),
      teamName: teamName.trim() || null,
      region: region.trim() || null,
      email: email.trim() || null,
      agentId: agentId.trim() || null,
    };

    setSaving(true);
    setError(null);
    try {
      if (person) {
        await api.updateSalesperson(person.id, payload);
      } else {
        await api.addSalesperson(payload);
      }
      await onSaved();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{person ? 'Edit salesperson' : 'Add salesperson'}</DialogTitle>
          <DialogDescription>
            The agent ID links this person to the transcript source when that field becomes available downstream.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => void submit(event)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="person-name">Full name</Label>
            <Input id="person-name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="person-team">Team</Label>
              <Input id="person-team" value={teamName} onChange={(e) => setTeamName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="person-region">Region</Label>
              <Input id="person-region" value={region} onChange={(e) => setRegion(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="person-email">Email</Label>
              <Input id="person-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="person-agent">Agent ID</Label>
              <Input id="person-agent" value={agentId} onChange={(e) => setAgentId(e.target.value)} />
            </div>
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
              {saving ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
