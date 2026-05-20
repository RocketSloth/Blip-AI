'use client';

import { useCallback, useRef, useState } from 'react';
import { clsx } from 'clsx';
import {
  uploadFiles,
  type UploadFilesResult,
} from '@/lib/actions/files';

type Props = {
  bundleId: string;
  onComplete: (result: UploadFilesResult) => void;
};

export default function FileUploader({ bundleId, onComplete }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      if (list.length === 0) return;
      setBusy(true);
      try {
        const fd = new FormData();
        for (const f of list) {
          fd.append('files', f, f.name);
        }
        const result = await uploadFiles(bundleId, fd);
        onComplete(result);
      } catch (err) {
        onComplete({
          uploaded: 0,
          overwritten: 0,
          rejected: list.map((f) => ({
            path: f.name,
            reason: err instanceof Error ? err.message : 'Upload failed',
          })),
        });
      } finally {
        setBusy(false);
        if (inputRef.current) inputRef.current.value = '';
      }
    },
    [bundleId, onComplete]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        if (e.dataTransfer.files?.length) {
          void handleFiles(e.dataTransfer.files);
        }
      }}
      className={clsx(
        'rounded-lg border border-dashed p-4 text-center transition',
        dragOver ? 'border-accent bg-muted' : 'border-border'
      )}
    >
      <p className="text-xs text-muted-foreground">
        Drop files here or
      </p>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        className="mt-1 text-xs font-medium text-accent hover:underline disabled:opacity-50"
      >
        {busy ? 'Uploading…' : 'browse'}
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        onChange={(e) => {
          if (e.target.files?.length) {
            void handleFiles(e.target.files);
          }
        }}
      />
      <p className="mt-2 text-[10px] text-muted-foreground">
        Up to 1MB per file. Duplicates overwrite.
      </p>
    </div>
  );
}
