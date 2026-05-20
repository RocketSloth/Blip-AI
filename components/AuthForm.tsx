'use client';

import { useFormStatus } from 'react-dom';
import { signInWithEmail } from '@/app/login/actions';
import Button from './ui/Button';
import Input from './ui/Input';

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending} className="w-full">
      {pending ? 'Sending…' : 'Send magic link'}
    </Button>
  );
}

export default function AuthForm({
  sent,
  error,
}: {
  sent: boolean;
  error?: string;
}) {
  return (
    <form action={signInWithEmail} className="space-y-4">
      <div>
        <label htmlFor="email" className="block text-sm font-medium">
          Email
        </label>
        <Input
          id="email"
          name="email"
          type="email"
          required
          autoComplete="email"
          autoFocus
          placeholder="you@example.com"
          className="mt-1"
        />
      </div>

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-500 bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-200"
        >
          {error}
        </p>
      ) : null}

      {sent ? (
        <p
          role="status"
          className="rounded-md border border-green-500 bg-green-50 px-3 py-2 text-sm text-green-700 dark:bg-green-950 dark:text-green-200"
        >
          Check your email for the magic link.
        </p>
      ) : null}

      <SubmitButton />
    </form>
  );
}
