import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md text-sm font-medium whitespace-nowrap transition-all outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:opacity-90",
        destructive:
          "bg-destructive text-white hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:bg-destructive/60 dark:focus-visible:ring-destructive/40",
        outline:
          "border border-border bg-background shadow-xs hover:bg-accent hover:text-accent-foreground dark:border-input dark:bg-input/30 dark:hover:bg-input/50",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "border border-transparent hover:bg-muted",
        link: "text-primary underline-offset-4 hover:underline",
        // Solid semantic variants — bordered, colored text, tinted hover.
        success:
          "border border-[color:color-mix(in_srgb,var(--status-success)_45%,transparent)] text-[var(--status-success)] bg-transparent hover:bg-[var(--status-success-bg)]",
        warning:
          "border border-[color:color-mix(in_srgb,var(--status-warning)_45%,transparent)] text-[var(--status-warning)] bg-transparent hover:bg-[var(--status-warning-bg)]",
        info: "border border-border text-primary bg-transparent hover:bg-muted hover:text-primary",
        danger:
          "border border-[color:color-mix(in_srgb,var(--destructive)_45%,transparent)] text-destructive bg-transparent hover:bg-destructive/10",
        // Ghost + semantic color combos — transparent at rest, tinted hover, no border.
        // Preserves the original hand-rolled Button's `.ghost.success` etc. combinations
        // (icon-only action buttons in action-buttons.tsx and registration-footer.tsx),
        // which shadcn's single-axis variant model has no built-in way to express.
        "success-ghost": "border border-transparent text-[var(--ok)] hover:bg-[var(--ok-bg)]",
        "warning-ghost": "border border-transparent text-[var(--warn)] hover:bg-[var(--warn-bg)]",
        "info-ghost": "border border-transparent text-primary hover:bg-muted",
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        xs: "h-6 gap-1 rounded-md px-2 text-xs has-[>svg]:px-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 gap-1.5 rounded-md px-3 has-[>svg]:px-2.5",
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4",
        icon: "size-9",
        "icon-xs": "size-6 rounded-md [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-8",
        "icon-lg": "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  type = "button",
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot.Root : "button";

  return (
    <Comp
      type={type}
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
