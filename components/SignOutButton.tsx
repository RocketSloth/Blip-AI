export default function SignOutButton() {
  return (
    <form action="/auth/sign-out" method="post">
      <button
        type="submit"
        className="rounded-md border border-border px-3 py-1.5 text-xs font-medium transition hover:bg-muted"
      >
        Sign out
      </button>
    </form>
  );
}
