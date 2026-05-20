import { createClient } from '@/lib/supabase/server';
import type { FileRow, FileSummary } from './types';

export async function listFiles(bundleId: string): Promise<FileSummary[]> {
  const supabase = createClient();
  const { data, error } = await supabase
    .from('files')
    .select('id, path, size_bytes, mime_type, updated_at')
    .eq('bundle_id', bundleId)
    .order('path', { ascending: true });

  if (error) throw new Error(error.message);
  return (data as FileSummary[] | null) ?? [];
}

export async function getFile(fileId: string): Promise<FileRow | null> {
  const supabase = createClient();
  const { data, error } = await supabase
    .from('files')
    .select('*')
    .eq('id', fileId)
    .maybeSingle();

  if (error) throw new Error(error.message);
  return (data as FileRow | null) ?? null;
}

export async function getFilesForExport(
  bundleId: string
): Promise<Pick<FileRow, 'path' | 'content'>[]> {
  const supabase = createClient();
  const { data, error } = await supabase
    .from('files')
    .select('path, content')
    .eq('bundle_id', bundleId)
    .order('path', { ascending: true });

  if (error) throw new Error(error.message);
  return (data as Pick<FileRow, 'path' | 'content'>[] | null) ?? [];
}
