import Link from 'next/link';
import { redirect } from 'next/navigation';
import AuthForm from '@/components/AuthForm';
import { createClient } from '@/lib/supabase/server';

export default async function LoginPage({
  searchParams,
}: {
  searchParams: { sent?: string; error?: string };
}) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (user) redirect('/app');

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-16">
      <Link
        href="/"
        className="text-sm uppercase tracking-widest text-muted-foreground hover:text-foreground"
      >
        ← AI Vault
      </Link>
      <h1 className="mt-4 text-3xl font-semibold">Sign in</h1>
      <p className="mt-2 text-muted-foreground">
        We&apos;ll email you a magic link. No password to remember.
      </p>
      <div className="mt-8">
        <AuthForm
          sent={searchParams.sent === '1'}
          error={searchParams.error}
        />
      </div>
    </main>
  );
}
