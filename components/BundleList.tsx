import Link from 'next/link';
import type { BundleWithFileCount } from '@/lib/db/types';
import BundleCard from './BundleCard';

export default function BundleList({
  bundles,
}: {
  bundles: BundleWithFileCount[];
}) {
  if (bundles.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-10 text-center">
        <h2 className="text-lg font-medium">No bundles yet</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          A bundle is a group of files — like &ldquo;My Claude Setup&rdquo;.
          Create one to start adding files.
        </p>
        <Link
          href="/app/bundles/new"
          className="mt-4 inline-flex items-center justify-center rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition hover:opacity-90"
        >
          Create your first bundle
        </Link>
      </div>
    );
  }

  return (
    <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {bundles.map((bundle) => (
        <li key={bundle.id}>
          <BundleCard bundle={bundle} />
        </li>
      ))}
    </ul>
  );
}
