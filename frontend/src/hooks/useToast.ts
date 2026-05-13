import { useState, useEffect, useCallback } from 'react';

export interface ToastMessage {
  id: string;
  title?: string;
  description?: string;
  variant?: 'default' | 'destructive';
}

type ToastListener = (t: ToastMessage) => void;

const listeners = new Set<ToastListener>();
let counter = 0;

export function toast(opts: Omit<ToastMessage, 'id'>) {
  const msg: ToastMessage = { ...opts, id: String(++counter) };
  listeners.forEach((fn) => fn(msg));
}

export function useToast() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  useEffect(() => {
    const handler: ToastListener = (t) => {
      setToasts((prev) => [...prev, t]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((x) => x.id !== t.id));
      }, 5000);
    };
    listeners.add(handler);
    return () => {
      listeners.delete(handler);
    };
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((x) => x.id !== id));
  }, []);

  return { toasts, dismiss };
}
