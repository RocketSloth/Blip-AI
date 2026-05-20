import { createClient } from '@/lib/supabase/server';
import type { Bundle, BundleWithFileCount } from './types';

export async function listBundles(): Promise<BundleWithFileCount[]> {
  const supabase = createClient();

  const { data: bundles, error } = await supabase
    .from('bundles')
    .select('*')
    .order('updated_at', { ascending: false });

  if (error) throw new Error(error.message);
  if (!bundles || bundles.length === 0) return [];

  const ids = bundles.map((b) => b.id);
  const { data: files, error: fileError } = await supabase
    .from('files')
    .select('bundle_id')
    .in('bundle_id', ids);

  if (fileError) throw new Error(fileError.message);

  const counts = new Map<string, number>();
  for (const f of files ?? []) {
    counts.set(f.bundle_id, (counts.get(f.bundle_id) ?? 0) + 1);
  }

  return bundles.map((b) => ({
    ...(b as Bundle),
    file_count: counts.get(b.id) ?? 0,
  }));
}

export async function getBundle(bundleId: string): Promise<Bundle | null> {
  const supabase = createClient();
  const { data, error } = await supabase
    .from('bundles')
    .select('*')
    .eq('id', bundleId)
    .maybeSingle();

  if (error) throw new Error(error.message);
  return (data as Bundle | null) ?? null;
}
