import Link from 'next/link';
import { createBundle } from '@/lib/actions/bundles';

export default function NewBundlePage() {
  return (
    <main className="mx-auto max-w-xl px-6 py-10">
      <Link
        href="/app"
        className="text-sm uppercase tracking-widest text-muted-foreground hover:text-foreground"
      >
        ← Bundles
      </Link>
      <h1 className="mt-3 text-2xl font-semibold">New bundle</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Give your bundle a name. You can rename or describe it later.
      </p>
      <form action={createBundle} className="mt-8 space-y-5">
        <div>
          <label htmlFor="name" className="block text-sm font-medium">
            Name
          </label>
          <input
            id="name"
            name="name"
            required
            maxLength={120}
            autoFocus
            placeholder="My Claude Setup"
            className="mt-1 block w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <div>
          <label htmlFor="description" className="block text-sm font-medium">
            Description <span className="text-muted-foreground">(optional)</span>
          </label>
          <textarea
            id="description"
            name="description"
            rows={3}
            placeholder="What's in this bundle?"
            className="mt-1 block w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <div className="flex gap-3">
          <button
            type="submit"
            className="inline-flex items-center justify-center rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition hover:opacity-90"
          >
            Create bundle
          </button>
          <Link
            href="/app"
            className="inline-flex items-center justify-center rounded-md border border-border px-4 py-2 text-sm font-medium transition hover:bg-muted"
          >
            Cancel
          </Link>
        </div>
      </form>
    </main>
  );
}
