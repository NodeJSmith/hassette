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
        // Neutral control with no visible border (the transparent one keeps its height level with
        // bordered siblings): muted at rest, highlight tint on hover.
        ghost:
          "border border-transparent bg-transparent text-muted-foreground hover:bg-[var(--highlight-bg)] hover:text-foreground",
        // Text actions: `link` for the primary one, `link-muted` for secondary ones.
        link: "text-primary underline-offset-4 hover:underline",
        "link-muted": "text-muted-foreground underline-offset-4 hover:text-foreground hover:underline",
        // Outlined semantic variants — toned border and text, transparent fill, tinted hover.
        success:
          "border border-[color:color-mix(in_srgb,var(--status-success)_45%,transparent)] text-[var(--status-success)] bg-transparent hover:bg-[var(--status-success-bg)]",
        warning:
          "border border-[color:color-mix(in_srgb,var(--status-warning)_45%,transparent)] text-[var(--status-warning)] bg-transparent hover:bg-[var(--status-warning-bg)]",
        info: "border border-border text-primary bg-transparent hover:bg-muted hover:text-primary",
        danger:
          "border border-[color:color-mix(in_srgb,var(--destructive)_45%,transparent)] text-destructive bg-transparent hover:bg-destructive/10",
        // Ghost with a semantic tone: transparent at rest, tone-tinted hover, no visible border. Separate
        // variants because cva's single variant axis can't combine `ghost` with a tone.
        "success-ghost": "border border-transparent text-[var(--ok)] hover:bg-[var(--ok-bg)]",
        "warning-ghost": "border border-transparent text-[var(--warn)] hover:bg-[var(--warn-bg)]",
        "info-ghost": "border border-transparent text-primary hover:bg-muted",
        // `ghost` with a resting border, for a control that stands alone rather than inside a
        // denser surface. Unlike `outline` it has no fill or shadow of its own.
        subtle:
          "border border-border bg-transparent text-muted-foreground hover:bg-[var(--highlight-bg)] hover:text-foreground",
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
        // No box (height, padding, border) and the surrounding font size: for controls that sit
        // on a line of text without changing that line's height.
        inline: "h-auto gap-1 border-0 p-0 text-[length:inherit] [&_svg:not([class*='size-'])]:size-3",
      },
      // Grow to the touch-target minimum on narrow (no persistent sidebar) layouts.
      touch: {
        true: "max-sidebar:min-h-[var(--size-touch)] max-sidebar:min-w-[var(--size-touch)]",
        false: "",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
      touch: false,
    },
  },
);

function Button({
  className,
  variant = "default",
  size = "default",
  touch,
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
      className={cn(buttonVariants({ variant, size, touch, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
