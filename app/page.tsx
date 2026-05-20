import Link from 'next/link';

export default function LandingPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-16">
      <div className="space-y-8">
        <header>
          <p className="text-sm uppercase tracking-widest text-muted-foreground">
            AI Vault
          </p>
          <h1 className="mt-3 text-5xl font-semibold leading-tight">
            GitHub for AI files.
          </h1>
        </header>
        <p className="max-w-xl text-lg text-muted-foreground">
          A private vault for the configs that bring a new AI system up to
          speed — <span className="font-mono">soul.md</span>, skills, MCP
          configs, agent definitions. Group them into bundles, edit them in the
          browser, download the bundle as a zip whenever you spin up a fresh
          system.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link
            href="/login"
            className="inline-flex items-center justify-center rounded-md bg-accent px-5 py-2.5 text-sm font-medium text-accent-foreground transition hover:opacity-90"
          >
            Sign in
          </Link>
          <Link
            href="/app"
            className="inline-flex items-center justify-center rounded-md border border-border px-5 py-2.5 text-sm font-medium transition hover:bg-muted"
          >
            Open your vault
          </Link>
        </div>
        <dl className="grid grid-cols-1 gap-6 pt-8 sm:grid-cols-3">
          <div>
            <dt className="text-sm font-medium">Bundles</dt>
            <dd className="mt-1 text-sm text-muted-foreground">
              Group files like &ldquo;My Claude Setup&rdquo; or &ldquo;Coding
              Agent v3&rdquo;.
            </dd>
          </div>
          <div>
            <dt className="text-sm font-medium">Editor</dt>
            <dd className="mt-1 text-sm text-muted-foreground">
              Paste, drop, or edit Markdown / JSON / YAML in the browser.
            </dd>
          </div>
          <div>
            <dt className="text-sm font-medium">Export</dt>
            <dd className="mt-1 text-sm text-muted-foreground">
              Download the whole bundle as a zip and drop it into a fresh AI.
            </dd>
          </div>
        </dl>
      </div>
    </main>
  );
}
