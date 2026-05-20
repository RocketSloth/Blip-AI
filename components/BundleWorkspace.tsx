'use client';

import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import FileEditor from './FileEditor';
import FileList from './FileList';
import FileUploader from './FileUploader';
import { ToastProvider, useToast } from './ui/Toast';
import Button from './ui/Button';
import Dialog from './ui/Dialog';
import Input from './ui/Input';
import { createFile } from '@/lib/actions/files';
import type { FileRow, FileSummary } from '@/lib/db/types';

type Props = {
  bundleId: string;
  files: FileSummary[];
  selectedFile: FileRow | null;
};

function WorkspaceInner({ bundleId, files, selectedFile }: Props) {
  const router = useRouter();
  const toast = useToast();
  const [creating, setCreating] = useState(false);

  const handleSelect = useCallback(
    (fileId: string) => {
      router.push(`/app/bundles/${bundleId}?file=${fileId}`);
    },
    [bundleId, router]
  );

  const handleCreated = useCallback(
    (fileId: string) => {
      setCreating(false);
      router.push(`/app/bundles/${bundleId}?file=${fileId}`);
      router.refresh();
    },
    [bundleId, router]
  );

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px_1fr]">
      <aside className="space-y-4">
        <div className="flex gap-2">
          <Button size="sm" onClick={() => setCreating(true)}>
            New file
          </Button>
        </div>
        <FileUploader
          bundleId={bundleId}
          onComplete={(summary) => {
            const parts: string[] = [];
            if (summary.uploaded) parts.push(`${summary.uploaded} uploaded`);
            if (summary.overwritten)
              parts.push(`${summary.overwritten} overwritten`);
            if (summary.rejected.length)
              parts.push(`${summary.rejected.length} rejected`);
            toast.push(
              parts.length ? parts.join(', ') : 'Nothing uploaded',
              summary.rejected.length ? 'error' : 'success'
            );
            for (const r of summary.rejected) {
              toast.push(`Rejected ${r.path}: ${r.reason}`, 'error');
            }
            router.refresh();
          }}
        />
        <FileList
          bundleId={bundleId}
          files={files}
          selectedFileId={selectedFile?.id ?? null}
          onSelect={handleSelect}
          onDeleted={(deletedId) => {
            const remaining = files.filter((f) => f.id !== deletedId);
            const next = remaining[0]?.id;
            router.push(
              next
                ? `/app/bundles/${bundleId}?file=${next}`
                : `/app/bundles/${bundleId}`
            );
            router.refresh();
          }}
        />
      </aside>

      <section className="min-h-[60vh] rounded-lg border border-border bg-background">
        {selectedFile ? (
          <FileEditor key={selectedFile.id} file={selectedFile} />
        ) : (
          <div className="flex h-full min-h-[60vh] flex-col items-center justify-center p-10 text-center">
            <p className="text-base font-medium">No file selected</p>
            <p className="mt-1 max-w-sm text-sm text-muted-foreground">
              Create a new file or drag files onto the upload zone on the left
              to get started.
            </p>
            <Button className="mt-4" onClick={() => setCreating(true)}>
              New file
            </Button>
          </div>
        )}
      </section>

      <NewFileDialog
        open={creating}
        onClose={() => setCreating(false)}
        bundleId={bundleId}
        onCreated={handleCreated}
        onError={(message) => toast.push(message, 'error')}
      />
    </div>
  );
}

function NewFileDialog({
  open,
  onClose,
  bundleId,
  onCreated,
  onError,
}: {
  open: boolean;
  onClose: () => void;
  bundleId: string;
  onCreated: (fileId: string) => void;
  onError: (message: string) => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [path, setPath] = useState('soul.md');
  const [content, setContent] = useState('');

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.set('bundleId', bundleId);
      fd.set('path', path);
      fd.set('content', content);
      const result = await createFile(fd);
      onCreated(result.id);
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not create file');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="New file">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="file-path" className="block text-sm font-medium">
            Path
          </label>
          <Input
            id="file-path"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            required
            maxLength={512}
            autoFocus
            placeholder="skills/code-review.md"
            className="mt-1 font-mono text-xs"
          />
        </div>
        <div>
          <label htmlFor="file-content" className="block text-sm font-medium">
            Content <span className="text-muted-foreground">(optional)</span>
          </label>
          <textarea
            id="file-content"
            rows={6}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Write a starter, or leave blank to edit later."
            className="mt-1 block w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create'}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export default function BundleWorkspace(props: Props) {
  return (
    <ToastProvider>
      <WorkspaceInner {...props} />
    </ToastProvider>
  );
}
