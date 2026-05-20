'use client';

import { useState } from 'react';
import { clsx } from 'clsx';
import { deleteFile, renameFile } from '@/lib/actions/files';
import type { FileSummary } from '@/lib/db/types';
import Button from './ui/Button';
import Dialog from './ui/Dialog';
import Input from './ui/Input';
import { useToast } from './ui/Toast';

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

type Props = {
  bundleId: string;
  files: FileSummary[];
  selectedFileId: string | null;
  onSelect: (fileId: string) => void;
  onDeleted: (fileId: string) => void;
};

export default function FileList({
  bundleId: _bundleId,
  files,
  selectedFileId,
  onSelect,
  onDeleted,
}: Props) {
  const toast = useToast();
  const [renaming, setRenaming] = useState<FileSummary | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState<FileSummary | null>(
    null
  );

  return (
    <>
      <div className="rounded-lg border border-border bg-background">
        <div className="border-b border-border px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Files
        </div>
        {files.length === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-muted-foreground">
            No files yet.
          </p>
        ) : (
          <ul className="max-h-[55vh] overflow-y-auto">
            {files.map((file) => (
              <li key={file.id}>
                <button
                  type="button"
                  onClick={() => onSelect(file.id)}
                  className={clsx(
                    'flex w-full items-start justify-between gap-2 border-b border-border px-3 py-2 text-left text-xs transition last:border-b-0 hover:bg-muted',
                    selectedFileId === file.id && 'bg-muted'
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-mono text-[12px]">
                      {file.path}
                    </div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                      {formatBytes(file.size_bytes)}
                    </div>
                  </div>
                  <span className="flex shrink-0 gap-1">
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => {
                        e.stopPropagation();
                        setRenaming(file);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.stopPropagation();
                          setRenaming(file);
                        }
                      }}
                      className="rounded p-0.5 text-muted-foreground hover:bg-background hover:text-foreground"
                      aria-label="Rename file"
                      title="Rename"
                    >
                      ✎
                    </span>
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmingDelete(file);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.stopPropagation();
                          setConfirmingDelete(file);
                        }
                      }}
                      className="rounded p-0.5 text-muted-foreground hover:bg-background hover:text-red-600"
                      aria-label="Delete file"
                      title="Delete"
                    >
                      ×
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <RenameDialog
        file={renaming}
        onClose={() => setRenaming(null)}
        onError={(m) => toast.push(m, 'error')}
        onSuccess={() => {
          toast.push('Renamed', 'success');
          setRenaming(null);
        }}
      />

      <DeleteDialog
        file={confirmingDelete}
        onClose={() => setConfirmingDelete(null)}
        onError={(m) => toast.push(m, 'error')}
        onSuccess={(id) => {
          toast.push('Deleted', 'success');
          setConfirmingDelete(null);
          onDeleted(id);
        }}
      />
    </>
  );
}

function RenameDialog({
  file,
  onClose,
  onError,
  onSuccess,
}: {
  file: FileSummary | null;
  onClose: () => void;
  onError: (m: string) => void;
  onSuccess: () => void;
}) {
  const [path, setPath] = useState(file?.path ?? '');
  const [submitting, setSubmitting] = useState(false);

  if (!file) return null;

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.set('fileId', file.id);
      fd.set('path', path);
      await renameFile(fd);
      onSuccess();
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not rename');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title="Rename file">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="rename-path" className="block text-sm font-medium">
            New path
          </label>
          <Input
            id="rename-path"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            required
            maxLength={512}
            autoFocus
            className="mt-1 font-mono text-xs"
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
            {submitting ? 'Renaming…' : 'Rename'}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function DeleteDialog({
  file,
  onClose,
  onError,
  onSuccess,
}: {
  file: FileSummary | null;
  onClose: () => void;
  onError: (m: string) => void;
  onSuccess: (id: string) => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  if (!file) return null;

  const submit = async () => {
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.set('fileId', file.id);
      await deleteFile(fd);
      onSuccess(file.id);
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not delete');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title="Delete file">
      <p className="text-sm">
        Delete <span className="font-mono">{file.path}</span>? This can&apos;t
        be undone.
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button
          type="button"
          variant="secondary"
          onClick={onClose}
          disabled={submitting}
        >
          Cancel
        </Button>
        <Button
          type="button"
          variant="danger"
          onClick={submit}
          disabled={submitting}
        >
          {submitting ? 'Deleting…' : 'Delete'}
        </Button>
      </div>
    </Dialog>
  );
}
