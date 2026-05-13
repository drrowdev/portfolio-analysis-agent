import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { useActiveStrategy, useUpdateStrategy } from '@/hooks/useStrategies';
import { toast } from '@/hooks/useToast';
import { StrategyStep } from '@/components/wizard/StrategyStep';
import { Shield, RefreshCw, Pencil, Loader2, Target } from 'lucide-react';
import { Link } from '@tanstack/react-router';
import { strategyToFormData, toStrategyCreate } from '@/types/strategy';
import type { StrategyFormData, RiskTolerance } from '@/types/strategy';

function riskBadgeVariant(risk: RiskTolerance) {
  switch (risk) {
    case 'conservative':
      return 'secondary' as const;
    case 'moderate':
      return 'default' as const;
    case 'aggressive':
      return 'warning' as const;
  }
}

export function StrategyCard() {
  const { data: strategy, isLoading } = useActiveStrategy();
  const updateStrategy = useUpdateStrategy();
  const [editOpen, setEditOpen] = useState(false);
  const [editData, setEditData] = useState<StrategyFormData | null>(null);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Investment Strategy</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading…
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!strategy) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Investment Strategy</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Target className="h-4 w-4" />
              No strategy configured yet
            </div>
            <Link to="/wizard">
              <Button size="sm" variant="outline">
                Set up in Wizard
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    );
  }

  function handleEdit() {
    if (!strategy) return;
    setEditData(strategyToFormData(strategy));
    setEditOpen(true);
  }

  function handleSave() {
    if (!editData || !strategy) return;
    updateStrategy.mutate(
      { id: strategy.id, data: toStrategyCreate(editData) },
      {
        onSuccess: () => {
          setEditOpen(false);
          toast({ title: 'Strategy updated!' });
        },
        onError: (err) => {
          toast({
            title: 'Failed to update strategy',
            description: err.message,
            variant: 'destructive',
          });
        },
      },
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium">Investment Strategy</CardTitle>
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={handleEdit}>
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div>
              <div className="text-sm font-medium">{strategy.name}</div>
              {strategy.description && (
                <p className="text-xs text-muted-foreground mt-0.5">{strategy.description}</p>
              )}
            </div>

            <div className="flex items-center gap-2">
              <Shield className="h-3.5 w-3.5 text-muted-foreground" />
              <Badge variant={riskBadgeVariant(strategy.risk_tolerance)}>
                {strategy.risk_tolerance}
              </Badge>
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground">Target Allocation</div>
              {Object.entries(strategy.target_allocation).map(([cat, pct]) => (
                <div key={cat} className="flex justify-between text-xs">
                  <span className="capitalize text-foreground">{cat.replace(/_/g, ' ')}</span>
                  <span className="text-muted-foreground">{pct}%</span>
                </div>
              ))}
            </div>

            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <RefreshCw className="h-3 w-3" />
              <span>Rebalance at ±{strategy.rebalance_threshold_pct}%</span>
            </div>

            {strategy.tax_optimization_enabled && (
              <div className="text-xs text-emerald-500">✓ Tax optimization enabled</div>
            )}
          </div>
        </CardContent>
      </Card>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Edit Investment Strategy</DialogTitle>
            <DialogDescription>
              Update your strategy settings. Changes are saved immediately.
            </DialogDescription>
          </DialogHeader>
          {editData && <StrategyStep initialData={editData} onChange={setEditData} />}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setEditOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={updateStrategy.isPending}
              className="bg-emerald-600 hover:bg-emerald-700"
            >
              {updateStrategy.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving…
                </>
              ) : (
                'Save Changes'
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
