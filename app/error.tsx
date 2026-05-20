'use client';

import { useEffect } from 'react';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col items-start justify-center px-6 py-16">
      <p className="text-sm uppercase tracking-widest text-muted-foreground">
        Error
      </p>
      <h1 className="mt-2 text-3xl font-semibold">Something went wrong.</h1>
      <p className="mt-4 break-words text-sm text-muted-foreground">
        {error.message || 'Unknown error.'}
      </p>
      <button
        type="button"
        onClick={() => reset()}
        className="mt-6 inline-flex items-center justify-center rounded-md border border-border px-4 py-2 text-sm font-medium transition hover:bg-muted"
      >
        Try again
      </button>
    </main>
  );
}
