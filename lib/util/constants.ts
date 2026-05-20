export const MAX_FILE_BYTES = 1024 * 1024; // 1 MB — matches the size_bytes CHECK constraint.

export const ALLOWED_EXTENSIONS = new Set<string>([
  'md',
  'mdc',
  'txt',
  'json',
  'yaml',
  'yml',
  'toml',
  'env',
  'sh',
  'js',
  'ts',
  'tsx',
  'jsx',
  'py',
  'rb',
  'go',
  'rs',
  'java',
  'cs',
  'cpp',
  'c',
  'h',
  'hpp',
  'html',
  'css',
  'scss',
  'xml',
  'csv',
  'tsv',
  'log',
  'conf',
  'ini',
  'cfg',
  'gitignore',
  'dockerfile',
  'mcp',
]);

export const MIME_BY_EXT: Record<string, string> = {
  md: 'text/markdown',
  mdc: 'text/markdown',
  txt: 'text/plain',
  json: 'application/json',
  yaml: 'application/yaml',
  yml: 'application/yaml',
  toml: 'application/toml',
  html: 'text/html',
  css: 'text/css',
  js: 'text/javascript',
  ts: 'text/typescript',
  tsx: 'text/typescript',
  jsx: 'text/javascript',
  py: 'text/x-python',
  csv: 'text/csv',
  xml: 'application/xml',
};

export function mimeForPath(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  return MIME_BY_EXT[ext] ?? 'text/plain';
}
