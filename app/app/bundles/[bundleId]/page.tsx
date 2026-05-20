import Link from 'next/link';
import { notFound } from 'next/navigation';
import BundleWorkspace from '@/components/BundleWorkspace';
import { getBundle } from '@/lib/db/bundles';
import { getFile, listFiles } from '@/lib/db/files';

export const dynamic = 'force-dynamic';

export default async function BundleViewPage({
  params,
  searchParams,
}: {
  params: { bundleId: string };
  searchParams: { file?: string };
}) {
  const bundle = await getBundle(params.bundleId);
  if (!bundle) notFound();

  const files = await listFiles(bundle.id);
  const selectedId =
    (searchParams.file && files.find((f) => f.id === searchParams.file)?.id) ??
    files[0]?.id ??
    null;
  const selectedFile = selectedId ? await getFile(selectedId) : null;

  return (
    <main className="mx-auto flex max-w-7xl flex-col px-6 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            href="/app"
            className="text-xs uppercase tracking-widest text-muted-foreground hover:text-foreground"
          >
            ← Bundles
          </Link>
          <h1 className="mt-1 text-2xl font-semibold">{bundle.name}</h1>
          {bundle.description ? (
            <p className="mt-1 text-sm text-muted-foreground">
              {bundle.description}
            </p>
          ) : null}
        </div>
        <div className="flex gap-2">
          <Link
            href={`/app/bundles/${bundle.id}/settings`}
            className="inline-flex items-center justify-center rounded-md border border-border px-3 py-2 text-sm transition hover:bg-muted"
          >
            Settings
          </Link>
          <a
            href={`/api/bundles/${bundle.id}/export`}
            download
            className="inline-flex items-center justify-center rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-foreground transition hover:opacity-90"
          >
            Export ZIP
          </a>
        </div>
      </div>

      <div className="mt-6">
        <BundleWorkspace
          bundleId={bundle.id}
          files={files}
          selectedFile={selectedFile}
        />
      </div>
    </main>
  );
}
