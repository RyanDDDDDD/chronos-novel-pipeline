import { useEffect, useRef } from 'react'
import type * as React from 'react'
import { Command, CommandEmpty, CommandGroup, CommandItem, CommandList } from '@/shared/components/ui/command'
import { Popover, PopoverAnchor, PopoverContent } from '@/shared/components/ui/popover'
import { cn } from '@/shared/utils/cn'

export interface FilterMenuItem {
  id: string
  label: string
  sublabel?: string
}

export function FilterMenu({
  open,
  items,
  highlightedId,
  onSelect,
  onOpenChange,
  emptyText = '无匹配项',
  anchor,
  side = 'top',
}: {
  open: boolean
  items: FilterMenuItem[]
  highlightedId?: string
  onSelect: (id: string) => void
  onOpenChange: (open: boolean) => void
  emptyText?: string
  /** Element to anchor the popover to (typically wraps the triggering input). */
  anchor?: React.ReactNode
  side?: 'top' | 'bottom' | 'left' | 'right'
}) {
  const listRef = useRef<HTMLDivElement>(null)

  // cmdk only schedules its own scrollIntoView from its internal setState('value', ...)
  // path (native pointer-hover/keyboard handling inside the Command's own DOM subtree).
  // Our highlightedId is keyboard-driven from the external textarea and only ever reaches
  // cmdk through the controlled `value` prop, which takes a different internal path that
  // just re-renders without scheduling a scroll — so ArrowUp/ArrowDown never scrolls the
  // highlighted item into view on its own; do it ourselves.
  useEffect(() => {
    if (!highlightedId) return
    listRef.current
      ?.querySelector('[data-highlighted="true"]')
      ?.scrollIntoView({ block: 'nearest' })
  }, [highlightedId])

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      {anchor ? <PopoverAnchor asChild>{anchor}</PopoverAnchor> : <PopoverAnchor />}
      <PopoverContent
        align="start"
        side={side}
        sideOffset={4}
        onOpenAutoFocus={(e) => e.preventDefault()}
        className="w-[--radix-popover-trigger-width] p-0"
      >
        {/* Controlled value keeps cmdk's own data-selected in sync with our keyboard-driven
         * highlightedId; otherwise it defaults to the first item and never moves on ArrowUp/Down
         * since those keydowns land on the external textarea, outside this Command's DOM subtree. */}
        <Command value={highlightedId ?? ''} onValueChange={() => {}}>
          <CommandList ref={listRef} className="max-h-56">
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup>
              {items.map((item) => (
                <CommandItem
                  key={item.id}
                  value={item.id}
                  // Items are plain (non-focusable) divs, so a real mousedown would shift
                  // focus to <body> and away from the triggering textarea. Radix Popover's
                  // DismissableLayer treats that focus-outside as a dismiss signal and fires
                  // onOpenChange(false) -> onSelect('') *before* the click's own onSelect(id)
                  // lands, racing with (and sometimes wiping) the real selection. Keeping
                  // focus on the textarea sidesteps the race entirely.
                  onMouseDown={(e) => e.preventDefault()}
                  onSelect={() => onSelect(item.id)}
                  data-highlighted={highlightedId === item.id ? 'true' : undefined}
                  className={cn(
                    highlightedId === item.id && 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)]',
                  )}
                >
                  <span className="font-medium">{item.label}</span>
                  {item.sublabel && (
                    <span className="ml-2 text-xs text-[color:var(--c-text-faint)]">{item.sublabel}</span>
                  )}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
