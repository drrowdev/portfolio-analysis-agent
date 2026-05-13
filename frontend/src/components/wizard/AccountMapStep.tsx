import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

const mockAccounts = [
  { id: '1', name: 'Nordnet AOT', detected: 'arvo-osuustili' },
  { id: '2', name: 'Nordnet OST', detected: 'osakesäästötili' },
];

const accountTypes = [
  { value: 'arvo_osuustili', label: 'Arvo-osuustili (AOT)' },
  { value: 'osakesaastotili', label: 'Osakesäästötili (OST)' },
  { value: 'espp', label: 'ESPP' },
];

export function AccountMapStep() {
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        We detected the following accounts in your CSV files. Please confirm the account types:
      </p>
      <div className="space-y-4">
        {mockAccounts.map((account) => (
          <div key={account.id} className="flex items-center justify-between rounded-lg border border-border p-4">
            <div>
              <p className="font-medium text-foreground">{account.name}</p>
              <p className="text-xs text-muted-foreground">Detected: {account.detected}</p>
            </div>
            <Select defaultValue="arvo_osuustili">
              <SelectTrigger className="w-[200px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {accountTypes.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    {type.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ))}
      </div>
    </div>
  );
}
