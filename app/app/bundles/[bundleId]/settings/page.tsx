import Link from 'next/link';
import { notFound } from 'next/navigation';
import { deleteBundle, renameBundle } from '@/lib/actions/bundles';
import { getBundle } from '@/lib/db/bundles';

export const dynamic = 'force-dynamic';

export default async function BundleSettingsPage({
  params,
}: {
  params: { bundleId: string };
}) {
  const bundle = await getBundle(params.bundleId);
  if (!bundle) notFound();

  return (
    <main className="mx-auto max-w-xl px-6 py-10">
      <Link
        href={`/app/bundles/${bundle.id}`}
        className="text-xs uppercase tracking-widest text-muted-foreground hover:text-foreground"
      >
        ← {bundle.name}
      </Link>
      <h1 className="mt-2 text-2xl font-semibold">Bundle settings</h1>

      <section className="mt-8 space-y-4 rounded-lg border border-border p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Details
        </h2>
        <form action={renameBundle} className="space-y-4">
          <input type="hidden" name="bundleId" value={bundle.id} />
          <div>
            <label htmlFor="name" className="block text-sm font-medium">
              Name
            </label>
            <input
              id="name"
              name="name"
              defaultValue={bundle.name}
              required
              maxLength={120}
              className="mt-1 block w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <div>
            <label htmlFor="description" className="block text-sm font-medium">
              Description
            </label>
            <textarea
              id="description"
              name="description"
              rows={3}
              defaultValue={bundle.description}
              className="mt-1 block w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <button
            type="submit"
            className="inline-flex items-center justify-center rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition hover:opacity-90"
          >
            Save changes
          </button>
        </form>
      </section>

      <section className="mt-6 space-y-4 rounded-lg border border-border p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-red-600">
          Danger zone
        </h2>
        <p className="text-sm text-muted-foreground">
          Deleting a bundle also deletes every file inside it. This cannot be
          undone.
        </p>
        <form action={deleteBundle}>
          <input type="hidden" name="bundleId" value={bundle.id} />
          <button
            type="submit"
            className="inline-flex items-center justify-center rounded-md border border-red-500 px-4 py-2 text-sm font-medium text-red-600 transition hover:bg-red-50 dark:hover:bg-red-950"
          >
            Delete bundle
          </button>
        </form>
      </section>
    </main>
  );
}
