import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // Fail open if env vars are missing so the app can still render the
  // landing page (which will surface a configuration error). Crashing here
  // would turn every request into a 500 / MIDDLEWARE_INVOCATION_FAILED.
  if (!url || !anonKey) {
    if (process.env.NODE_ENV !== 'production') {
      console.warn(
        '[ai-vault] Skipping Supabase session refresh: NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY not set'
      );
    }
    return response;
  }

  try {
    const supabase = createServerClient(url, anonKey, {
      cookies: {
        get(name: string) {
          return request.cookies.get(name)?.value;
        },
        set(name: string, value: string, options: CookieOptions) {
          request.cookies.set({ name, value, ...options });
          response = NextResponse.next({ request });
          response.cookies.set({ name, value, ...options });
        },
        remove(name: string, options: CookieOptions) {
          request.cookies.set({ name, value: '', ...options });
          response = NextResponse.next({ request });
          response.cookies.set({ name, value: '', ...options });
        },
      },
    });

    await supabase.auth.getUser();
  } catch (err) {
    console.error('[ai-vault] Supabase session refresh failed:', err);
  }

  return response;
}
