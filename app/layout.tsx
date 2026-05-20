import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AI Vault',
  description:
    'Store the config files that bring a new AI system up to speed, then re-import them later.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
