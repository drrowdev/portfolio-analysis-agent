import { useState, useCallback } from 'react';
import { WizardContainer } from '@/components/wizard/WizardContainer';
import { UploadStep } from '@/components/wizard/UploadStep';
import { AccountMapStep } from '@/components/wizard/AccountMapStep';
import { StrategyStep } from '@/components/wizard/StrategyStep';
import { useNavigate } from '@tanstack/react-router';
import { useCreateStrategy } from '@/hooks/useStrategies';
import { toast } from '@/hooks/useToast';
import { toStrategyCreate } from '@/types/strategy';
import type { StrategyFormData } from '@/types/strategy';

export function WizardPage() {
  const navigate = useNavigate();
  const createStrategy = useCreateStrategy();
  const [strategyData, setStrategyData] = useState<StrategyFormData | null>(null);

  const handleStrategyChange = useCallback((data: StrategyFormData) => {
    setStrategyData(data);
  }, []);

  function handleComplete() {
    if (!strategyData) {
      toast({ title: 'Please fill in your strategy', variant: 'destructive' });
      return;
    }
    createStrategy.mutate(toStrategyCreate(strategyData), {
      onSuccess: () => {
        toast({ title: 'Strategy saved successfully!' });
        navigate({ to: '/' });
      },
      onError: (error) => {
        toast({
          title: 'Failed to save strategy',
          description: error.message,
          variant: 'destructive',
        });
      },
    });
  }

  const wizardSteps = [
    {
      title: 'Upload Transactions',
      description: 'Upload your broker CSV/PDF files to get started.',
      component: <UploadStep />,
    },
    {
      title: 'Map Accounts',
      description: 'Confirm the account types detected from your files.',
      component: <AccountMapStep />,
    },
    {
      title: 'Investment Strategy',
      description: 'Tell us about your investment goals and preferences.',
      component: <StrategyStep onChange={handleStrategyChange} />,
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-foreground">Import Wizard</h2>
        <p className="text-sm text-muted-foreground">Set up your portfolio in a few easy steps</p>
      </div>
      <WizardContainer
        steps={wizardSteps}
        onComplete={handleComplete}
        isSubmitting={createStrategy.isPending}
      />
    </div>
  );
}
