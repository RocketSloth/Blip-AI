import { NextResponse, type NextRequest } from 'next/server';
import { createClient } from '@/lib/supabase/server';
import { getBundle } from '@/lib/db/bundles';
import { getFilesForExport } from '@/lib/db/files';
import { slugify } from '@/lib/util/filename';
import { buildZip } from '@/lib/util/zip';

export const runtime = 'nodejs';

export async function GET(
  _request: NextRequest,
  { params }: { params: { bundleId: string } }
): Promise<NextResponse> {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const bundle = await getBundle(params.bundleId);
  if (!bundle || bundle.owner_id !== user.id) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  const files = await getFilesForExport(bundle.id);
  const zipBuffer = await buildZip(files);
  const filename = `${slugify(bundle.name)}.zip`;
  const body = new Uint8Array(zipBuffer);

  return new NextResponse(body, {
    status: 200,
    headers: {
      'Content-Type': 'application/zip',
      'Content-Disposition': `attachment; filename="${filename}"`,
      'Content-Length': String(body.byteLength),
      'Cache-Control': 'no-store',
    },
  });
}
