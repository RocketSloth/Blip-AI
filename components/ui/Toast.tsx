'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { clsx } from 'clsx';

type ToastKind = 'info' | 'success' | 'error';
type Toast = { id: number; kind: ToastKind; message: string };

type ToastContextValue = {
  push: (message: string, kind?: ToastKind) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((message: string, kind: ToastKind = 'info') => {
    setToasts((prev) => [...prev, { id: Date.now() + Math.random(), kind, message }]);
  }, []);

  useEffect(() => {
    if (toasts.length === 0) return;
    const timer = setTimeout(() => {
      setToasts((prev) => prev.slice(1));
    }, 4000);
    return () => clearTimeout(timer);
  }, [toasts]);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={clsx(
              'pointer-events-auto max-w-sm rounded-md border px-3 py-2 text-sm shadow-md',
              t.kind === 'success' &&
                'border-green-500 bg-green-50 text-green-900 dark:bg-green-950 dark:text-green-100',
              t.kind === 'error' &&
                'border-red-500 bg-red-50 text-red-900 dark:bg-red-950 dark:text-red-100',
              t.kind === 'info' && 'border-border bg-background'
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside ToastProvider');
  return ctx;
}
