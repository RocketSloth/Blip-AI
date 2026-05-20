'use client';

import { useState } from 'react';
import { createBundle } from '@/lib/actions/bundles';
import Button from './ui/Button';
import Dialog from './ui/Dialog';
import Input from './ui/Input';

export default function NewBundleDialog() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button onClick={() => setOpen(true)}>New bundle</Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="New bundle">
        <form action={createBundle} className="space-y-4">
          <div>
            <label htmlFor="bundle-name" className="block text-sm font-medium">
              Name
            </label>
            <Input
              id="bundle-name"
              name="name"
              required
              maxLength={120}
              autoFocus
              placeholder="My Claude Setup"
              className="mt-1"
            />
          </div>
          <div>
            <label
              htmlFor="bundle-description"
              className="block text-sm font-medium"
            >
              Description
            </label>
            <textarea
              id="bundle-description"
              name="description"
              rows={3}
              placeholder="What's in this bundle?"
              className="mt-1 block w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit">Create</Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
