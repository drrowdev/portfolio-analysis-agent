import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import {
  useGoals,
  useCreateGoal,
  useUpdateGoal,
  useDeleteGoal,
} from '@/hooks/useGoals';
import type { GoalCreatePayload, GoalProjection } from '@/hooks/useGoals';
import { toast } from '@/hooks/useToast';
import { Target, Plus, Pencil, Trash2, TrendingUp, Loader2, Banknote, CalendarClock } from 'lucide-react';
import { usePrivacy } from '@/contexts/PrivacyContext';
import { StrategyCard } from '@/components/strategy/StrategyCard';

function formatEur(value: number, masked = false): string {
  if (masked) return '•••••';
  return new Intl.NumberFormat('fi-FI', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(value);
}

function formatDate(iso: string): string {
  const [y, m, d] = iso.split('-');
  return `${d}.${m}.${y}`;
}

function formatYearsMonths(months: number): string {
  const y = Math.floor(months / 12);
  const m = months % 12;
  if (y === 0) return `${m}mo`;
  if (m === 0) return `${y}y`;
  return `${y}y ${m}mo`;
}

const defaultForm: GoalCreatePayload = {
  name: '',
  target_amount_eur: 1000000,
  target_date: '',
  assumed_annual_return_pct: 7,
  notes: '',
};

function GoalForm({
  initial,
  onSave,
  onCancel,
  isPending,
}: {
  initial: GoalCreatePayload;
  onSave: (data: GoalCreatePayload) => void;
  onCancel: () => void;
  isPending: boolean;
}) {
  const [form, setForm] = useState<GoalCreatePayload>(initial);

  return (
    <div className="space-y-4">
      <div>
        <label className="text-sm font-medium">Goal Name</label>
        <Input
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="e.g. Reach €1M portfolio"
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="text-sm font-medium">Target Amount (€)</label>
          <Input
            type="number"
            value={form.target_amount_eur}
            onChange={(e) => setForm({ ...form, target_amount_eur: Number(e.target.value) })}
          />
        </div>
        <div>
          <label className="text-sm font-medium">Target Date</label>
          <Input
            type="date"
            value={form.target_date}
            onChange={(e) => setForm({ ...form, target_date: e.target.value })}
          />
        </div>
      </div>
      <div>
        <label className="text-sm font-medium">Assumed Annual Return (%)</label>
        <Input
          type="number"
          step="0.5"
          value={form.assumed_annual_return_pct}
          onChange={(e) => setForm({ ...form, assumed_annual_return_pct: Number(e.target.value) })}
        />
      </div>
      <div>
        <label className="text-sm font-medium">Notes (optional)</label>
        <Input
          value={form.notes ?? ''}
          onChange={(e) => setForm({ ...form, notes: e.target.value || undefined })}
          placeholder="Any notes about this goal…"
        />
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <Button variant="outline" onClick={onCancel}>Cancel</Button>
        <Button
          onClick={() => onSave(form)}
          disabled={isPending || !form.name || !form.target_date}
          className="bg-emerald-600 hover:bg-emerald-700"
        >
          {isPending ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Saving…</> : 'Save Goal'}
        </Button>
      </div>
    </div>
  );
}

function GoalCard({ proj, onEdit, onDelete }: {
  proj: GoalProjection;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { privacyMode } = usePrivacy();
  const g = proj.goal;
  const progressCapped = Math.min(proj.progress_pct, 100);
  const onTrack = proj.shortfall_no_contributions <= 0;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div>
            <CardTitle className="text-base">{g.name}</CardTitle>
            <p className="text-xs text-muted-foreground mt-0.5">
              Target: {formatEur(g.target_amount_eur, privacyMode)} by {formatDate(g.target_date)}
              <span className="ml-2">({formatYearsMonths(proj.months_remaining)} left)</span>
            </p>
          </div>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onEdit}>
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0 text-destructive" onClick={onDelete}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Progress bar */}
        <div>
          <div className="flex justify-between text-sm mb-1.5">
            <span className="text-muted-foreground">Progress</span>
            <span className="font-medium">{proj.progress_pct.toFixed(1)}%</span>
          </div>
          <Progress value={progressCapped} className="h-3" />
          <div className="flex justify-between text-xs text-muted-foreground mt-1">
            <span>{formatEur(proj.current_value_eur, privacyMode)}</span>
            <span>{formatEur(g.target_amount_eur, privacyMode)}</span>
          </div>
        </div>

        {/* Projection cards */}
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border p-3">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
              <TrendingUp className="h-3.5 w-3.5" />
              Projected ({g.assumed_annual_return_pct}% p.a.)
            </div>
            <div className="text-sm font-semibold">
              {formatEur(proj.projected_value_no_contributions, privacyMode)}
            </div>
            {onTrack ? (
              <Badge variant="default" className="mt-1.5 text-xs bg-emerald-600">On track</Badge>
            ) : (
              <Badge variant="destructive" className="mt-1.5 text-xs">
                Gap: {formatEur(proj.shortfall_no_contributions, privacyMode)}
              </Badge>
            )}
          </div>

          <div className="rounded-lg border p-3">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
              <Banknote className="h-3.5 w-3.5" />
              Monthly needed
            </div>
            <div className="text-sm font-semibold">
              {proj.required_monthly_eur > 0
                ? formatEur(proj.required_monthly_eur, privacyMode) + '/mo'
                : '€0 — on track!'}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Extra contributions to reach goal
            </p>
          </div>

          <div className="rounded-lg border p-3">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
              <CalendarClock className="h-3.5 w-3.5" />
              Current gap
            </div>
            <div className="text-sm font-semibold">
              {formatEur(proj.gap_eur, privacyMode)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Remaining to target
            </p>
          </div>
        </div>

        {g.notes && (
          <p className="text-xs text-muted-foreground italic">{g.notes}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function GoalsPage() {
  const { data: goals, isLoading } = useGoals();
  const createGoal = useCreateGoal();
  const updateGoal = useUpdateGoal();
  const deleteGoal = useDeleteGoal();

  const [createOpen, setCreateOpen] = useState(false);
  const [editGoal, setEditGoal] = useState<GoalProjection | null>(null);

  function handleCreate(data: GoalCreatePayload) {
    createGoal.mutate(data, {
      onSuccess: () => {
        setCreateOpen(false);
        toast({ title: 'Goal created!' });
      },
      onError: (err) => toast({ title: 'Failed', description: err.message, variant: 'destructive' }),
    });
  }

  function handleUpdate(data: GoalCreatePayload) {
    if (!editGoal) return;
    updateGoal.mutate(
      { id: editGoal.goal.id, data },
      {
        onSuccess: () => {
          setEditGoal(null);
          toast({ title: 'Goal updated!' });
        },
        onError: (err) => toast({ title: 'Failed', description: err.message, variant: 'destructive' }),
      },
    );
  }

  function handleDelete(id: string) {
    deleteGoal.mutate(id, {
      onSuccess: () => toast({ title: 'Goal deleted' }),
      onError: (err) => toast({ title: 'Failed', description: err.message, variant: 'destructive' }),
    });
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-4 w-72 mt-2" />
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Investment Strategy */}
      <StrategyCard />

      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-foreground">Investment Goals</h2>
          <p className="text-sm text-muted-foreground">
            Track your targets and see what it takes to reach them
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)} className="bg-emerald-600 hover:bg-emerald-700">
          <Plus className="h-4 w-4 mr-2" />
          New Goal
        </Button>
      </div>

      {goals && goals.length > 0 ? (
        <div className="space-y-4">
          {goals.map((proj) => (
            <GoalCard
              key={proj.goal.id}
              proj={proj}
              onEdit={() => setEditGoal(proj)}
              onDelete={() => handleDelete(proj.goal.id)}
            />
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <Target className="h-12 w-12 text-muted-foreground/40 mb-4" />
            <p className="text-muted-foreground mb-4">No investment goals yet</p>
            <Button onClick={() => setCreateOpen(true)} className="bg-emerald-600 hover:bg-emerald-700">
              <Plus className="h-4 w-4 mr-2" />
              Create Your First Goal
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Create Investment Goal</DialogTitle>
            <DialogDescription>
              Set a target amount, date, and assumed return to see how much you need to invest monthly.
            </DialogDescription>
          </DialogHeader>
          <GoalForm
            initial={defaultForm}
            onSave={handleCreate}
            onCancel={() => setCreateOpen(false)}
            isPending={createGoal.isPending}
          />
        </DialogContent>
      </Dialog>

      {/* Edit dialog */}
      <Dialog open={!!editGoal} onOpenChange={(open) => !open && setEditGoal(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Edit Goal</DialogTitle>
            <DialogDescription>Update your goal parameters.</DialogDescription>
          </DialogHeader>
          {editGoal && (
            <GoalForm
              initial={{
                name: editGoal.goal.name,
                target_amount_eur: editGoal.goal.target_amount_eur,
                target_date: editGoal.goal.target_date,
                assumed_annual_return_pct: editGoal.goal.assumed_annual_return_pct,
                notes: editGoal.goal.notes ?? '',
              }}
              onSave={handleUpdate}
              onCancel={() => setEditGoal(null)}
              isPending={updateGoal.isPending}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
