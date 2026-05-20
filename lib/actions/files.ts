'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { createClient } from '@/lib/supabase/server';
import {
  assertAllowedExtension,
  sanitizePath,
} from '@/lib/util/filename';
import { MAX_FILE_BYTES, mimeForPath } from '@/lib/util/constants';

async function requireUser() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect('/login');
  return { supabase, user };
}

async function assertOwnsBundle(bundleId: string): Promise<void> {
  const { supabase } = await requireUser();
  const { data, error } = await supabase
    .from('bundles')
    .select('id')
    .eq('id', bundleId)
    .maybeSingle();
  if (error) throw new Error(error.message);
  if (!data) throw new Error('Bundle not found');
}

export type CreateFileResult = {
  id: string;
  path: string;
};

export async function createFile(formData: FormData): Promise<CreateFileResult> {
  const bundleId = String(formData.get('bundleId') ?? '');
  const rawPath = String(formData.get('path') ?? '');
  const content = String(formData.get('content') ?? '');

  if (!bundleId) throw new Error('Missing bundle id');

  const path = sanitizePath(rawPath);
  assertAllowedExtension(path);

  const sizeBytes = Buffer.byteLength(content, 'utf8');
  if (sizeBytes > MAX_FILE_BYTES) {
    throw new Error('File exceeds 1MB limit');
  }

  await assertOwnsBundle(bundleId);
  const { supabase, user } = await requireUser();

  const { data, error } = await supabase
    .from('files')
    .insert({
      bundle_id: bundleId,
      owner_id: user.id,
      path,
      content,
      size_bytes: sizeBytes,
      mime_type: mimeForPath(path),
    })
    .select('id, path')
    .single();

  if (error) {
    if (error.code === '23505') {
      throw new Error(`A file already exists at "${path}"`);
    }
    throw new Error(error.message);
  }

  revalidatePath(`/app/bundles/${bundleId}`);
  return { id: data.id, path: data.path };
}

export type UpdateFileResult = {
  id: string;
  updated_at: string;
};

export async function updateFile(formData: FormData): Promise<UpdateFileResult> {
  const fileId = String(formData.get('fileId') ?? '');
  const content = String(formData.get('content') ?? '');
  if (!fileId) throw new Error('Missing file id');

  const sizeBytes = Buffer.byteLength(content, 'utf8');
  if (sizeBytes > MAX_FILE_BYTES) {
    throw new Error('File exceeds 1MB limit');
  }

  const { supabase } = await requireUser();

  const { data, error } = await supabase
    .from('files')
    .update({ content, size_bytes: sizeBytes })
    .eq('id', fileId)
    .select('id, bundle_id, updated_at')
    .single();

  if (error) throw new Error(error.message);

  revalidatePath(`/app/bundles/${data.bundle_id}`);
  return { id: data.id, updated_at: data.updated_at };
}

export async function renameFile(formData: FormData): Promise<void> {
  const fileId = String(formData.get('fileId') ?? '');
  const rawPath = String(formData.get('path') ?? '');
  if (!fileId) throw new Error('Missing file id');

  const path = sanitizePath(rawPath);
  assertAllowedExtension(path);

  const { supabase } = await requireUser();

  const { data, error } = await supabase
    .from('files')
    .update({ path, mime_type: mimeForPath(path) })
    .eq('id', fileId)
    .select('bundle_id')
    .single();

  if (error) {
    if (error.code === '23505') {
      throw new Error(`A file already exists at "${path}"`);
    }
    throw new Error(error.message);
  }

  revalidatePath(`/app/bundles/${data.bundle_id}`);
}

export async function deleteFile(formData: FormData): Promise<void> {
  const fileId = String(formData.get('fileId') ?? '');
  if (!fileId) throw new Error('Missing file id');

  const { supabase } = await requireUser();

  const { data, error } = await supabase
    .from('files')
    .delete()
    .eq('id', fileId)
    .select('bundle_id')
    .single();

  if (error) throw new Error(error.message);

  revalidatePath(`/app/bundles/${data.bundle_id}`);
}

export type UploadFilesResult = {
  uploaded: number;
  overwritten: number;
  rejected: { path: string; reason: string }[];
};

export async function uploadFiles(
  bundleId: string,
  formData: FormData
): Promise<UploadFilesResult> {
  if (!bundleId) throw new Error('Missing bundle id');

  await assertOwnsBundle(bundleId);
  const { supabase, user } = await requireUser();

  const entries = formData.getAll('files');
  if (entries.length === 0) {
    return { uploaded: 0, overwritten: 0, rejected: [] };
  }

  // Look up existing paths to count overwrites without doing a follow-up query per file.
  const { data: existing, error: existingError } = await supabase
    .from('files')
    .select('path')
    .eq('bundle_id', bundleId);
  if (existingError) throw new Error(existingError.message);
  const existingPaths = new Set((existing ?? []).map((r) => r.path));

  const result: UploadFilesResult = { uploaded: 0, overwritten: 0, rejected: [] };

  for (const entry of entries) {
    if (!(entry instanceof File)) continue;
    const rawName = entry.name || 'untitled.txt';

    let path: string;
    try {
      path = sanitizePath(rawName);
      assertAllowedExtension(path);
    } catch (err) {
      result.rejected.push({
        path: rawName,
        reason: err instanceof Error ? err.message : 'Invalid path',
      });
      continue;
    }

    if (entry.size > MAX_FILE_BYTES) {
      result.rejected.push({ path, reason: 'Exceeds 1MB limit' });
      continue;
    }

    let content: string;
    try {
      content = await entry.text();
    } catch {
      result.rejected.push({ path, reason: 'Could not decode as text' });
      continue;
    }
    const sizeBytes = Buffer.byteLength(content, 'utf8');
    if (sizeBytes > MAX_FILE_BYTES) {
      result.rejected.push({ path, reason: 'Exceeds 1MB limit (after decode)' });
      continue;
    }

    const { error } = await supabase.from('files').upsert(
      {
        bundle_id: bundleId,
        owner_id: user.id,
        path,
        content,
        size_bytes: sizeBytes,
        mime_type: mimeForPath(path),
      },
      { onConflict: 'bundle_id,path' }
    );

    if (error) {
      result.rejected.push({ path, reason: error.message });
      continue;
    }

    if (existingPaths.has(path)) {
      result.overwritten += 1;
    } else {
      result.uploaded += 1;
      existingPaths.add(path);
    }
  }

  revalidatePath(`/app/bundles/${bundleId}`);
  return result;
}
