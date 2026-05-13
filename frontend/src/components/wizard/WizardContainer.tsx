import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Loader2 } from 'lucide-react';

interface WizardContainerProps {
  steps: {
    title: string;
    description: string;
    component: React.ReactNode;
  }[];
  onComplete: () => void;
  isSubmitting?: boolean;
}

export function WizardContainer({ steps, onComplete, isSubmitting }: WizardContainerProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const progress = (currentStep / steps.length) * 100;

  return (
    <Card className="max-w-2xl mx-auto">
      <CardHeader>
        <div className="space-y-4">
          <Progress value={progress} />
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>Step {currentStep + 1} of {steps.length}</span>
            <span>{Math.round(progress)}% complete</span>
          </div>
          <CardTitle>{steps[currentStep].title}</CardTitle>
          <CardDescription>{steps[currentStep].description}</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          {steps[currentStep].component}
          <div className="flex justify-between pt-4">
            <Button
              variant="outline"
              onClick={() => setCurrentStep((s) => Math.max(0, s - 1))}
              disabled={currentStep === 0 || isSubmitting}
            >
              Back
            </Button>
            {currentStep < steps.length - 1 ? (
              <Button onClick={() => setCurrentStep((s) => s + 1)}>
                Continue
              </Button>
            ) : (
              <Button
                onClick={onComplete}
                disabled={isSubmitting}
                className="bg-emerald-600 hover:bg-emerald-700"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Saving…
                  </>
                ) : (
                  'Complete Setup'
                )}
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
