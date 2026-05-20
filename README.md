# AI Vault

A private vault for the configuration files that bring a new AI system up to
speed — `soul.md`, skills, MCP configs, agent definitions, and so on. Group
them into **bundles**, edit them in the browser, and download a bundle as a
zip when you want to spin up a fresh AI.

This branch (`claude/ai-vault-mvp-AmxlJ`) holds the Next.js MVP. It is
permanently divergent from `main` (which keeps the unrelated original
project).

## Stack

- Next.js 14 (App Router) + TypeScript + Tailwind CSS
- Supabase Auth (magic-link email) + Postgres with row-level security
- CodeMirror 6 in-browser editor (Markdown / JSON / YAML)
- `jszip` for server-side ZIP export
- Deploy: Vercel

## Setup

### 1. Provision a Supabase project

1. Create a project at https://supabase.com.
2. In **Authentication → Providers**, enable **Email** with magic links and
   disable password.
3. In **Authentication → URL configuration → Redirect URLs**, add:
   - `http://localhost:3000/auth/callback`
   - `https://<your-vercel-domain>/auth/callback`
4. In **SQL Editor**, run `supabase/migrations/0001_init.sql`.

Verify policies (should be 8 rows):

```sql
select policyname from pg_policies where schemaname = 'public';
```

### 2. Configure environment variables

Copy `.env.example` to `.env.local` and fill in your Supabase values:

```
NEXT_PUBLIC_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOi...
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

No service-role key is needed. RLS + the user session cookie handle
authorisation for every read and write.

### 3. Run locally

```bash
npm install
npm run dev
```

Open <http://localhost:3000>.

## Useful scripts

```bash
npm run dev        # Next.js dev server
npm run build      # Production build
npm run start      # Run the production build
npm run lint       # ESLint via next lint
npm run typecheck  # tsc --noEmit
```

## Architecture

### Data model

Two tables in `public`, both RLS-enforced (owner-only).

- **`bundles`** — `id`, `owner_id` (`auth.users`), `name` (1–120 chars),
  `description`, `created_at`, `updated_at`.
- **`files`** — `id`, `bundle_id` (cascade), `owner_id`, `path` (1–512 chars,
  unique per bundle), `content` (text), `storage_kind` (`inline` / `storage`),
  `storage_path`, `size_bytes` (≤ 1 MB by `CHECK`), `mime_type`, timestamps.

Triggers auto-touch `updated_at` and bump the parent bundle's `updated_at`
whenever a file row changes.

**Why inline `text` for content (V1):** AI config files are small, the read
and write happen in a single round-trip, RLS stays uniform, and there are no
orphan blobs to garbage-collect. The 1 MB `CHECK` and `storage_kind` column
mean we can migrate large or binary files into Supabase Storage later
without a schema break.

### Auth flow

1. `/login` → server action calls
   `supabase.auth.signInWithOtp({ email, options: { emailRedirectTo } })`.
2. User clicks the email link → `/auth/callback?code=…`.
3. The callback route exchanges the code for a session and redirects to
   `/app`.
4. `middleware.ts` runs on every request and refreshes the Supabase session
   cookies via `supabase.auth.getUser()`.
5. `app/app/layout.tsx` is the auth gate — anonymous users are redirected
   to `/login`.
6. `POST /auth/sign-out` ends the session and redirects to `/`.

### File CRUD

All mutations live in `lib/actions/{bundles,files}.ts` as Server Actions:

- `createBundle`, `renameBundle`, `deleteBundle`
- `createFile`, `updateFile`, `renameFile`, `deleteFile`
- `uploadFiles(bundleId, FormData)` — multi-file, validates size and
  extension, sanitizes paths (no `..`, no absolute, no control chars), and
  **upserts on `(bundle_id, path)`** so duplicates overwrite. The action
  returns a structured summary (`uploaded`, `overwritten`, `rejected`) that
  the UI surfaces as toasts.

`next.config.mjs` bumps `experimental.serverActions.bodySizeLimit` to
`'4mb'` so a multi-file upload of small files fits. Individual files are
still capped at 1 MB by the DB constraint and validated client-side.

### Editor

`components/FileEditor.tsx` is a CodeMirror 6 client component. Language is
inferred from extension (`md`/`mdc` → Markdown, `json` → JSON, `yaml`/`yml`
→ YAML, anything else → plain). Saves are debounced 500 ms and `Cmd`/`Ctrl`
+ `S` flushes immediately. The save indicator shows `Unsaved` →
`Saving…` → `Saved`.

### ZIP export

`GET /api/bundles/[bundleId]/export` runs on the Node runtime, verifies
ownership, builds a `JSZip` with each file at its stored path, and streams
back `application/zip` with a `Content-Disposition: attachment` header. The
filename is `<slug(bundle.name)>.zip`. A plain `<a href download>` triggers
the download — no client JS required.

## Manual smoke test

After `npm install && npm run dev`, with the Supabase project provisioned
and `0001_init.sql` applied:

1. `npm run lint && npm run typecheck && npm run build` all pass.
2. In Supabase SQL editor, `select policyname from pg_policies where
   schemaname='public'` lists 8 policies.
3. Visit `/`, click **Sign in**, submit your email, click the magic link →
   lands on `/app`.
4. Create a bundle "My Claude Setup" → redirects to bundle view.
5. Drag in `soul.md` and `mcp.json` — both appear in the file list within
   ~1 s.
6. Click **New file** → enter `skills/code-review.md`, type content →
   "Saved" indicator appears.
7. Open `soul.md`, edit, wait 1 s, hard-refresh → content persists.
8. Click **Export ZIP** → browser downloads `my-claude-setup.zip` with all
   three files at their correct paths.
9. **Sign out** → navigating to `/app` redirects to `/login`. Sign back in →
   bundle and files still there.
10. Negative tests:
    - Navigate to a bundle id from a different account → 404 (RLS).
    - Upload a 5 MB file → rejected with a visible error toast.
11. Push the branch, open a Vercel preview, set the env vars, repeat
    steps 3, 5, 8 against the preview URL.

## Out of scope (V1)

- Public share links (per-file or per-bundle)
- Versioning / history
- Collaborators
- OAuth providers (Google, GitHub, …)
- Two-tab edit conflict resolution — last-write-wins is fine for V1.

## Known limits

- **Supabase free-tier email limits.** Fine for dev/demo; if you hit the
  wall, plug a Resend SMTP key into Supabase **Auth → SMTP**.
- **1 MB per file.** Sufficient for typical AI configs. The
  `storage_kind = 'storage'` migration path is reserved in the schema.
- **Two-tab edit conflicts.** Last-write-wins; add optimistic concurrency
  post-MVP if it bites.
