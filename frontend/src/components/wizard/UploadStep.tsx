import { useState, useCallback } from 'react';
import { Upload, FileText, CheckCircle2, AlertCircle, Loader2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useUploadNordnet, useUploadFidelity } from '@/hooks/usePortfolio';
import type { UploadResponse } from '@/types/portfolio';

type BrokerType = 'nordnet' | 'fidelity';
type NordnetAccountType = 'arvo_osuustili' | 'osakesaastotili';

interface FileEntry {
  file: File;
  broker: BrokerType;
  accountType?: NordnetAccountType;
}

interface UploadResult {
  fileName: string;
  success: boolean;
  response?: UploadResponse;
  error?: string;
}

function detectBroker(file: File): BrokerType {
  const name = file.name.toLowerCase();
  if (name.endsWith('.pdf')) return 'fidelity';
  return 'nordnet';
}

export function UploadStep() {
  const [fileEntries, setFileEntries] = useState<FileEntry[]>([]);
  const [results, setResults] = useState<UploadResult[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const uploadNordnet = useUploadNordnet();
  const uploadFidelity = useUploadFidelity();

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const newEntries: FileEntry[] = Array.from(e.target.files).map((file) => ({
        file,
        broker: detectBroker(file),
        accountType: detectBroker(file) === 'nordnet' ? 'arvo_osuustili' as NordnetAccountType : undefined,
      }));
      setFileEntries((prev) => [...prev, ...newEntries]);
    }
    e.target.value = '';
  }, []);

  const removeFile = useCallback((index: number) => {
    setFileEntries((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const updateAccountType = useCallback((index: number, accountType: NordnetAccountType) => {
    setFileEntries((prev) =>
      prev.map((entry, i) => (i === index ? { ...entry, accountType } : entry))
    );
  }, []);

  const updateBroker = useCallback((index: number, broker: BrokerType) => {
    setFileEntries((prev) =>
      prev.map((entry, i) => (i === index ? {
        ...entry,
        broker,
        accountType: broker === 'nordnet' ? 'arvo_osuustili' : undefined,
      } : entry))
    );
  }, []);

  const handleUpload = async () => {
    setIsUploading(true);
    setResults([]);
    const newResults: UploadResult[] = [];

    for (const entry of fileEntries) {
      try {
        let response: UploadResponse;
        if (entry.broker === 'nordnet') {
          response = await uploadNordnet.mutateAsync({
            file: entry.file,
            accountType: entry.accountType || 'arvo_osuustili',
          });
        } else {
          response = await uploadFidelity.mutateAsync({ file: entry.file });
        }
        newResults.push({ fileName: entry.file.name, success: true, response });
      } catch (err) {
        newResults.push({
          fileName: entry.file.name,
          success: false,
          error: err instanceof Error ? err.message : 'Upload failed',
        });
      }
    }

    setResults(newResults);
    setIsUploading(false);
    if (newResults.every((r) => r.success)) {
      setFileEntries([]);
    }
  };

  const totalLots = results.filter((r) => r.success).reduce((sum, r) => sum + (r.response?.lots_imported ?? 0), 0);
  const totalHoldings = results.filter((r) => r.success).reduce((sum, r) => sum + (r.response?.holdings_created ?? 0), 0);

  return (
    <div className="space-y-4">
      <div className="rounded-lg border-2 border-dashed border-border p-8 text-center">
        <Upload className="mx-auto h-10 w-10 text-muted-foreground" />
        <p className="mt-2 text-sm text-muted-foreground">
          Drag & drop your broker files here, or click to browse
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Supports Nordnet (.csv) and Fidelity (.pdf) export formats
        </p>
        <Button variant="outline" className="mt-4" asChild>
          <label>
            Browse Files
            <input
              type="file"
              accept=".csv,.pdf"
              multiple
              className="hidden"
              onChange={handleFileChange}
            />
          </label>
        </Button>
      </div>

      {fileEntries.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm font-medium text-foreground">Files to upload:</p>
          {fileEntries.map((entry, i) => (
            <div key={i} className="flex items-center gap-3 rounded-md bg-muted/50 p-3">
              <FileText className="h-4 w-4 text-muted-foreground flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <span className="text-sm text-foreground truncate block">{entry.file.name}</span>
                <span className="text-xs text-muted-foreground">({(entry.file.size / 1024).toFixed(1)} KB)</span>
              </div>
              <Select value={entry.broker} onValueChange={(v) => updateBroker(i, v as BrokerType)}>
                <SelectTrigger className="w-[130px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="nordnet">Nordnet</SelectItem>
                  <SelectItem value="fidelity">Fidelity</SelectItem>
                </SelectContent>
              </Select>
              {entry.broker === 'nordnet' && (
                <Select
                  value={entry.accountType || 'arvo_osuustili'}
                  onValueChange={(v) => updateAccountType(i, v as NordnetAccountType)}
                >
                  <SelectTrigger className="w-[180px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="arvo_osuustili">Arvo-osuustili (AOT)</SelectItem>
                    <SelectItem value="osakesaastotili">Osakesäästötili (OST)</SelectItem>
                  </SelectContent>
                </Select>
              )}
              <Button variant="ghost" size="icon" onClick={() => removeFile(i)} className="flex-shrink-0">
                <X className="h-4 w-4" />
              </Button>
            </div>
          ))}
          <Button
            onClick={handleUpload}
            disabled={isUploading || fileEntries.length === 0}
            className="w-full bg-emerald-600 hover:bg-emerald-700"
          >
            {isUploading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Uploading…
              </>
            ) : (
              <>
                <Upload className="mr-2 h-4 w-4" />
                Upload {fileEntries.length} file{fileEntries.length !== 1 ? 's' : ''}
              </>
            )}
          </Button>
        </div>
      )}

      {results.length > 0 && (
        <div className="space-y-2 rounded-lg border border-border p-4">
          <p className="text-sm font-medium text-foreground">Upload Results</p>
          {results.map((r, i) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              {r.success ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-500 mt-0.5 flex-shrink-0" />
              ) : (
                <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
              )}
              <div>
                <span className="text-foreground">{r.fileName}</span>
                {r.success && r.response && (
                  <span className="text-muted-foreground">
                    {' — '}{r.response.account_name}: {r.response.lots_imported} lots, {r.response.holdings_created} holdings
                  </span>
                )}
                {!r.success && (
                  <span className="text-red-400"> — {r.error}</span>
                )}
              </div>
            </div>
          ))}
          {results.some((r) => r.success) && (
            <div className="mt-3 pt-3 border-t border-border text-sm text-emerald-500">
              Total imported: {totalLots} lots across {totalHoldings} holdings
            </div>
          )}
        </div>
      )}
    </div>
  );
}
