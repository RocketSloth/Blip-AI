import JSZip from 'jszip';

export type ZipFileInput = {
  path: string;
  content: string;
};

export async function buildZip(files: ZipFileInput[]): Promise<Buffer> {
  const zip = new JSZip();
  for (const file of files) {
    zip.file(file.path, file.content);
  }
  return zip.generateAsync({
    type: 'nodebuffer',
    compression: 'DEFLATE',
    compressionOptions: { level: 6 },
  });
}
