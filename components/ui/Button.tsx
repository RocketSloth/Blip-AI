import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { clsx } from 'clsx';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';

const variants: Record<Variant, string> = {
  primary:
    'bg-accent text-accent-foreground hover:opacity-90 disabled:opacity-50',
  secondary:
    'border border-border bg-background hover:bg-muted disabled:opacity-50',
  ghost: 'hover:bg-muted disabled:opacity-50',
  danger:
    'border border-red-500 text-red-600 hover:bg-red-50 dark:hover:bg-red-950 disabled:opacity-50',
};

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: 'sm' | 'md';
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', className, ...rest },
  ref
) {
  return (
    <button
      ref={ref}
      className={clsx(
        'inline-flex items-center justify-center rounded-md font-medium transition focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-1 focus:ring-offset-background disabled:cursor-not-allowed',
        size === 'sm' ? 'px-2.5 py-1.5 text-xs' : 'px-4 py-2 text-sm',
        variants[variant],
        className
      )}
      {...rest}
    />
  );
});

export default Button;
