'use server';

import { redirect } from 'next/navigation';
import { createClient } from '@/lib/supabase/server';

export async function signInWithEmail(formData: FormData): Promise<void> {
  const email = String(formData.get('email') ?? '').trim();
  if (!email || !email.includes('@')) {
    redirect('/login?error=Please%20enter%20a%20valid%20email');
  }

  const supabase = createClient();
  const appUrl =
    process.env.NEXT_PUBLIC_APP_URL ?? 'http://localhost:3000';

  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: {
      emailRedirectTo: `${appUrl}/auth/callback`,
    },
  });

  if (error) {
    redirect(`/login?error=${encodeURIComponent(error.message)}`);
  }

  redirect('/login?sent=1');
}
