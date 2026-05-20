'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { createClient } from '@/lib/supabase/server';

async function requireUser() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect('/login');
  return { supabase, user };
}

export async function createBundle(formData: FormData): Promise<void> {
  const rawName = String(formData.get('name') ?? '').trim();
  const rawDescription = String(formData.get('description') ?? '').trim();

  if (rawName.length === 0) throw new Error('Bundle name is required');
  if (rawName.length > 120) throw new Error('Bundle name is too long (max 120 chars)');

  const { supabase, user } = await requireUser();

  const { data, error } = await supabase
    .from('bundles')
    .insert({
      owner_id: user.id,
      name: rawName,
      description: rawDescription,
    })
    .select('id')
    .single();

  if (error) throw new Error(error.message);

  revalidatePath('/app');
  redirect(`/app/bundles/${data.id}`);
}

export async function renameBundle(formData: FormData): Promise<void> {
  const bundleId = String(formData.get('bundleId') ?? '');
  const rawName = String(formData.get('name') ?? '').trim();
  const rawDescription = String(formData.get('description') ?? '').trim();

  if (!bundleId) throw new Error('Missing bundle id');
  if (rawName.length === 0) throw new Error('Bundle name is required');
  if (rawName.length > 120) throw new Error('Bundle name is too long (max 120 chars)');

  const { supabase } = await requireUser();

  const { error } = await supabase
    .from('bundles')
    .update({ name: rawName, description: rawDescription })
    .eq('id', bundleId);

  if (error) throw new Error(error.message);

  revalidatePath('/app');
  revalidatePath(`/app/bundles/${bundleId}`);
  revalidatePath(`/app/bundles/${bundleId}/settings`);
}

export async function deleteBundle(formData: FormData): Promise<void> {
  const bundleId = String(formData.get('bundleId') ?? '');
  if (!bundleId) throw new Error('Missing bundle id');

  const { supabase } = await requireUser();

  const { error } = await supabase.from('bundles').delete().eq('id', bundleId);
  if (error) throw new Error(error.message);

  revalidatePath('/app');
  redirect('/app');
}
