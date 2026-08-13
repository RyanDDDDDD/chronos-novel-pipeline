import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/shared/utils/cn"

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md text-sm font-medium whitespace-nowrap transition-all outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "bg-[var(--c-accent)] text-[var(--c-accent-text)] hover:bg-[var(--c-accent-hover)]",
        accent:
          "border border-[var(--c-accent)] bg-[var(--c-accent-subtle)] text-[var(--c-accent)] hover:border-[var(--c-accent)] hover:bg-[var(--c-accent-subtle)] hover:text-[var(--c-accent)]",
        destructive:
          "bg-destructive text-white hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:bg-destructive/60 dark:focus-visible:ring-destructive/40",
        outline:
          "border border-[var(--c-tag-violet-border)] bg-[var(--c-surface)] text-[var(--c-text-secondary)] shadow-xs hover:border-[var(--c-accent)] hover:bg-[var(--c-accent-subtle)] hover:text-[var(--c-accent)] aria-pressed:border-[var(--c-accent)] aria-pressed:bg-[var(--c-accent-subtle)] aria-pressed:text-[var(--c-accent)] aria-pressed:hover:border-[var(--c-accent)] aria-pressed:hover:bg-[var(--c-accent-subtle)] aria-pressed:hover:text-[var(--c-accent)]",
        secondary:
          "bg-[var(--c-surface-muted)] text-[var(--c-text-secondary)] hover:bg-[var(--c-surface-hover)] hover:text-[var(--c-text)]",
        ghost:
          "text-[var(--c-text-secondary)] hover:bg-[var(--c-surface-hover)] hover:text-[var(--c-text)]",
        link:
          "text-[var(--c-accent)] underline-offset-4 hover:text-[var(--c-accent-hover)] hover:underline",
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
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  )
}

export { Button, buttonVariants }
