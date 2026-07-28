import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground [a&]:hover:bg-primary/90",
        secondary: "bg-secondary text-secondary-foreground [a&]:hover:bg-secondary/90",
        destructive:
          "bg-destructive text-white focus-visible:ring-destructive/20 dark:bg-destructive/60 dark:focus-visible:ring-destructive/40 [a&]:hover:bg-destructive/90",
        outline: "border-border text-foreground [a&]:hover:bg-accent [a&]:hover:text-accent-foreground",
        ghost: "[a&]:hover:bg-accent [a&]:hover:text-accent-foreground",
        link: "text-primary underline-offset-4 [a&]:hover:underline",
        // Status-style badges (formerly BadgeVariant)
        success: "bg-[var(--ok-bg)] text-[var(--ok)]",
        warning: "bg-[var(--warn-bg)] text-[var(--warn)]",
        danger: "bg-destructive/10 text-destructive",
        info: "bg-primary/10 text-primary",
        neutral: "bg-muted text-muted-foreground",
        // Chip-style badges (formerly ChipVariant), merged in flat form.
        job: "border border-[var(--job-border)] bg-[var(--job-bg)] font-mono text-[var(--job)]",
        listener: "border border-[var(--listener-border)] bg-[var(--listener)]/10 font-mono text-[var(--listener)]",
        origin: "border border-border font-mono tracking-wide text-muted-foreground uppercase",
        muted: "border border-border bg-muted font-mono text-muted-foreground",
        // Chip "kind" sub-variants (formerly variant="kind" kind={ChipKind}), flattened —
        // one literal variant per StatusKind value instead of a discriminated union.
        "kind-ok": "border border-[var(--ok)] text-[var(--ok)]",
        "kind-warn": "border border-[var(--warn)] text-[var(--warn)]",
        "kind-err": "border border-destructive text-destructive",
        "kind-cancel": "border border-[var(--cancel)] text-[var(--cancel)]",
        "kind-mute": "border border-border text-muted-foreground",
      },
      size: {
        default: "",
        xs: "px-1.5 py-0 text-[11px]",
        sm: "px-2 py-0.5 text-xs",
        md: "px-2.5 py-1 text-sm",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

function Badge({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span";

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
