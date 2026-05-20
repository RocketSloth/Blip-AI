import { forwardRef, type InputHTMLAttributes } from 'react';
import { clsx } from 'clsx';

type InputProps = InputHTMLAttributes<HTMLInputElement>;

const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, ...rest },
  ref
) {
  return (
    <input
      ref={ref}
      className={clsx(
        'block w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent',
        className
      )}
      {...rest}
    />
  );
});

export default Input;
