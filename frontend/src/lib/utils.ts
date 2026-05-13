import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Convert string decimals from API to numbers recursively */
export function coerceNumbers<T>(obj: T): T {
  if (obj === null || obj === undefined) return obj;
  if (Array.isArray(obj)) return obj.map(coerceNumbers) as T;
  if (typeof obj === 'object') {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
      result[key] = coerceNumbers(value);
    }
    return result as T;
  }
  if (typeof obj === 'string' && /^-?\d+(\.\d+)?$/.test(obj)) {
    return Number(obj) as T;
  }
  return obj;
}

export function formatCurrency(value: number | string, currency = 'EUR'): string {
  const num = typeof value === 'string' ? Number(value) : value;
  return new Intl.NumberFormat('fi-FI', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num);
}

export function formatPercent(value: number | string): string {
  const num = typeof value === 'string' ? Number(value) : value;
  const sign = num >= 0 ? '+' : '';
  return `${sign}${num.toFixed(2)}%`;
}

export function formatNumber(value: number | string, decimals = 2): string {
  const num = typeof value === 'string' ? Number(value) : value;
  return new Intl.NumberFormat('fi-FI', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(num);
}

/** Format a date string as a human-friendly relative time. */
export function formatRelativeDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDays = Math.floor(diffHr / 24);

  if (diffSec < 60) return 'Just now';
  if (diffMin < 60) return `${diffMin} min ago`;
  if (diffHr < 24) return `${diffHr} hour${diffHr > 1 ? 's' : ''} ago`;
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return `${diffDays} days ago`;

  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
