import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { cva, type VariantProps } from 'class-variance-authority';
import { X } from 'lucide-react';
import { cn } from '../lib/utils';

const buttonVariants = cva('button', { variants: { variant: { primary: 'button-primary', secondary: 'button-secondary', ghost: 'button-ghost', danger: 'button-danger' }, size: { normal: '', small: 'button-small', icon: 'button-icon' } }, defaultVariants: { variant: 'primary', size: 'normal' } });
export const Button = React.forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants> & { asChild?: boolean }>(({ className, variant, size, asChild, ...props }, ref) => {
  const Comp = asChild ? Slot : 'button';
  return <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />;
});
Button.displayName = 'Button';
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => <input className={cn('input', className)} ref={ref} {...props} />);
Input.displayName = 'Input';
export function Badge({ children, tone = 'neutral', className = '' }: { children: React.ReactNode; tone?: 'neutral' | 'success' | 'warning' | 'error'; className?: string }) { return <span className={cn('badge', `badge-${tone}`, className)}>{children}</span>; }
export function Dialog({ open, onOpenChange, title, description, closeLabel, children, triggerRef }: { open: boolean; onOpenChange: (v: boolean) => void; title: string; description: string; closeLabel: string; children: React.ReactNode; triggerRef?: React.RefObject<HTMLElement | null> }) {
  return <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}><DialogPrimitive.Portal><DialogPrimitive.Overlay className="dialog-overlay" /><DialogPrimitive.Content className="dialog-content" onCloseAutoFocus={event => { if (triggerRef?.current?.isConnected) { event.preventDefault(); triggerRef.current.focus(); } }}><DialogPrimitive.Title className="dialog-title">{title}</DialogPrimitive.Title><DialogPrimitive.Description className="dialog-description">{description}</DialogPrimitive.Description>{children}<DialogPrimitive.Close asChild><Button variant="ghost" size="icon" className="dialog-close" aria-label={closeLabel}><X aria-hidden="true" size={20} /></Button></DialogPrimitive.Close></DialogPrimitive.Content></DialogPrimitive.Portal></DialogPrimitive.Root>;
}
