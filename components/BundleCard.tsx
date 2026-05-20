import Link from 'next/link';
import type { BundleWithFileCount } from '@/lib/db/types';

function formatUpdated(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const diffMs = Date.now() - d.getTime();
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString();
}

export default function BundleCard({
  bundle,
}: {
  bundle: BundleWithFileCount;
}) {
  return (
    <Link
      href={`/app/bundles/${bundle.id}`}
      className="block h-full rounded-lg border border-border bg-background p-5 transition hover:border-accent hover:shadow-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="truncate text-base font-semibold">{bundle.name}</h3>
        <span className="shrink-0 rounded bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
          {bundle.file_count} {bundle.file_count === 1 ? 'file' : 'files'}
        </span>
      </div>
      {bundle.description ? (
        <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">
          {bundle.description}
        </p>
      ) : (
        <p className="mt-2 text-sm italic text-muted-foreground">
          No description
        </p>
      )}
      <p className="mt-3 text-xs text-muted-foreground">
        Updated {formatUpdated(bundle.updated_at)}
      </p>
    </Link>
  );
}
