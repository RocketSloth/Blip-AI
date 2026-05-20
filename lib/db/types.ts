export type Bundle = {
  id: string;
  owner_id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
};

export type BundleWithFileCount = Bundle & {
  file_count: number;
};

export type StorageKind = 'inline' | 'storage';

export type FileRow = {
  id: string;
  bundle_id: string;
  owner_id: string;
  path: string;
  content: string;
  storage_kind: StorageKind;
  storage_path: string | null;
  size_bytes: number;
  mime_type: string;
  created_at: string;
  updated_at: string;
};

export type FileSummary = Pick<
  FileRow,
  'id' | 'path' | 'size_bytes' | 'mime_type' | 'updated_at'
>;
