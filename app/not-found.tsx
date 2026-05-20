import Link from 'next/link';

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col items-start justify-center px-6 py-16">
      <p className="text-sm uppercase tracking-widest text-muted-foreground">
        404
      </p>
      <h1 className="mt-2 text-3xl font-semibold">Nothing here.</h1>
      <p className="mt-4 text-muted-foreground">
        That bundle or file either doesn&apos;t exist or isn&apos;t yours.
      </p>
      <Link
        href="/app"
        className="mt-6 inline-flex items-center justify-center rounded-md border border-border px-4 py-2 text-sm font-medium transition hover:bg-muted"
      >
        Back to your vault
      </Link>
    </main>
  );
}
