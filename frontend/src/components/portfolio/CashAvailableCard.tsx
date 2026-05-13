import { useState, useRef, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Card, CardContent } from '@/components/ui/card';
import { Banknote } from 'lucide-react';
import { formatCurrency } from '@/lib/utils';
import { usePrivacy } from '@/contexts/PrivacyContext';

export function CashAvailableCard() {
  const { mask, privacyMode } = usePrivacy();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const { data } = useQuery({
    queryKey: ['setting', 'cash_available'],
    queryFn: () => api.getSetting('cash_available'),
  });

  const mutation = useMutation({
    mutationFn: (value: string) => api.setSetting('cash_available', value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['setting', 'cash_available'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      setEditing(false);
    },
  });

  const cashValue = data?.value ? parseFloat(data.value) : 0;

  function startEdit() {
    setDraft(cashValue > 0 ? cashValue.toString() : '');
    setEditing(true);
  }

  function save() {
    const num = parseFloat(draft);
    if (!isNaN(num) && num >= 0) {
      mutation.mutate(num.toString());
    } else {
      setEditing(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') save();
    if (e.key === 'Escape') setEditing(false);
  }

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  return (
    <Card>
      <CardContent className="p-3 sm:p-6">
        <div className="flex items-center justify-between">
          <div className="space-y-1 min-w-0">
            <p className="text-sm text-muted-foreground">Cash Available</p>
            {editing ? (
              <input
                ref={inputRef}
                type="number"
                min="0"
                step="any"
                className="w-full text-xl sm:text-2xl font-bold bg-transparent border-b-2 border-amber-500 outline-none text-amber-500 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={save}
                onKeyDown={handleKeyDown}
              />
            ) : (
              <p
                className="text-xl sm:text-2xl font-bold text-amber-500 cursor-pointer hover:opacity-80"
                onClick={startEdit}
                title="Click to edit"
              >
                {privacyMode ? mask(0) : formatCurrency(cashValue)}
              </p>
            )}
          </div>
          <div className="hidden sm:block rounded-full p-3 bg-amber-500/10">
            <Banknote className="h-5 w-5 text-amber-500" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
