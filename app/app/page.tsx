import Link from 'next/link';
import BundleList from '@/components/BundleList';
import { listBundles } from '@/lib/db/bundles';

export const dynamic = 'force-dynamic';

export default async function DashboardPage() {
  const bundles = await listBundles();

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Your bundles</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Each bundle is a group of files you can edit, upload to, or
            download as a zip.
          </p>
        </div>
        <Link
          href="/app/bundles/new"
          className="inline-flex items-center justify-center rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition hover:opacity-90"
        >
          New bundle
        </Link>
      </div>
      <div className="mt-8">
        <BundleList bundles={bundles} />
      </div>
    </main>
  );
}
