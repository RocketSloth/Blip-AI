'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { json } from '@codemirror/lang-json';
import { markdown } from '@codemirror/lang-markdown';
import { yaml } from '@codemirror/lang-yaml';
import { EditorView } from '@codemirror/view';
import { updateFile } from '@/lib/actions/files';
import { extensionOf } from '@/lib/util/filename';
import { MAX_FILE_BYTES } from '@/lib/util/constants';
import type { FileRow } from '@/lib/db/types';
import { useToast } from './ui/Toast';

const SAVE_DEBOUNCE_MS = 500;

type SaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error';

function languageFor(path: string) {
  switch (extensionOf(path)) {
    case 'md':
    case 'mdc':
      return [markdown()];
    case 'json':
      return [json()];
    case 'yaml':
    case 'yml':
      return [yaml()];
    default:
      return [];
  }
}

export default function FileEditor({ file }: { file: FileRow }) {
  const toast = useToast();
  const [value, setValue] = useState(file.content);
  const [state, setState] = useState<SaveState>('idle');
  const lastSavedRef = useRef(file.content);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setValue(file.content);
    lastSavedRef.current = file.content;
    setState('idle');
  }, [file.id, file.content]);

  const save = useCallback(
    async (next: string) => {
      if (next === lastSavedRef.current) {
        setState('idle');
        return;
      }
      const bytes = new TextEncoder().encode(next).length;
      if (bytes > MAX_FILE_BYTES) {
        setState('error');
        toast.push('File exceeds 1MB limit — change not saved', 'error');
        return;
      }
      setState('saving');
      try {
        const fd = new FormData();
        fd.set('fileId', file.id);
        fd.set('content', next);
        await updateFile(fd);
        lastSavedRef.current = next;
        setState('saved');
      } catch (err) {
        setState('error');
        toast.push(
          err instanceof Error ? err.message : 'Could not save',
          'error'
        );
      }
    },
    [file.id, toast]
  );

  const scheduleSave = useCallback(
    (next: string) => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        void save(next);
      }, SAVE_DEBOUNCE_MS);
    },
    [save]
  );

  const handleChange = useCallback(
    (next: string) => {
      setValue(next);
      if (next === lastSavedRef.current) {
        setState('idle');
        if (timerRef.current) clearTimeout(timerRef.current);
        return;
      }
      setState('dirty');
      scheduleSave(next);
    },
    [scheduleSave]
  );

  // Flush save on Cmd/Ctrl+S
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'S')) {
        e.preventDefault();
        if (timerRef.current) clearTimeout(timerRef.current);
        void save(value);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [save, value]);

  // Flush save on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const extensions = useMemo(
    () => [...languageFor(file.path), EditorView.lineWrapping],
    [file.path]
  );

  const sizeBytes = useMemo(
    () => new TextEncoder().encode(value).length,
    [value]
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-2 text-xs">
        <div className="min-w-0 flex-1 truncate font-mono text-muted-foreground">
          {file.path}
        </div>
        <div className="flex items-center gap-3 text-muted-foreground">
          <span>{formatBytes(sizeBytes)}</span>
          <SaveIndicator state={state} />
        </div>
      </div>
      <div className="min-h-[60vh] flex-1 overflow-hidden">
        <CodeMirror
          value={value}
          height="100%"
          extensions={extensions}
          onChange={handleChange}
          basicSetup={{
            lineNumbers: true,
            highlightActiveLine: true,
            foldGutter: false,
            autocompletion: false,
          }}
          theme="light"
        />
      </div>
    </div>
  );
}

function SaveIndicator({ state }: { state: SaveState }) {
  switch (state) {
    case 'dirty':
      return <span className="text-amber-600">Unsaved…</span>;
    case 'saving':
      return <span>Saving…</span>;
    case 'saved':
      return <span className="text-green-600">Saved</span>;
    case 'error':
      return <span className="text-red-600">Save failed</span>;
    case 'idle':
    default:
      return <span>Saved</span>;
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}
