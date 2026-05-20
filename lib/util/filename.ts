import { ALLOWED_EXTENSIONS } from './constants';

export function sanitizePath(input: string): string {
  let path = input.trim().replace(/\\/g, '/');
  path = path.replace(/^\/+/, '');

  if (path.length === 0) throw new Error('Path is empty');
  if (path.length > 512) throw new Error('Path is too long (max 512 chars)');
  if (path.split('/').some((seg) => seg === '..')) {
    throw new Error('Path may not contain ".."');
  }
  if (/^[a-zA-Z]:/.test(path)) {
    throw new Error('Absolute paths are not allowed');
  }
  if (path.split('/').some((seg) => seg.length === 0)) {
    throw new Error('Path contains an empty segment');
  }

  // eslint-disable-next-line no-control-regex
  if (/[\x00-\x1f\x7f]/.test(path)) {
    throw new Error('Path contains control characters');
  }

  return path;
}

export function extensionOf(path: string): string {
  const base = path.split('/').pop() ?? '';
  const dot = base.lastIndexOf('.');
  if (dot <= 0) return '';
  return base.slice(dot + 1).toLowerCase();
}

export function assertAllowedExtension(path: string): void {
  const ext = extensionOf(path);
  if (ext === '') return; // dotless files like "Dockerfile" pass.
  if (!ALLOWED_EXTENSIONS.has(ext)) {
    throw new Error(`File type ".${ext}" is not allowed`);
  }
}

export function slugify(input: string): string {
  const cleaned = input
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
  return cleaned || 'bundle';
}
