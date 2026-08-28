import { useEffect, useRef, useState } from 'react'
import { Loader2, CheckCircle2 } from 'lucide-react'
import { useSelector } from 'react-redux'
import { selectBackgroundJobs } from '@/shared/store/backgroundJobsSlice'
import { useActiveNovelId } from '@/shared/queries/novels'

const COLLAPSE_DELAY_MS = 3000
const FINISH_FLASH_MS = 1500

/** Full pill (icon + label) when `compact` is false; a small icon-only square when true.
 * `variant` picks the icon: a spinning Loader2 while running, a static emerald CheckCircle2
 * during the post-completion flash. `compact` is where the "stop blocking the corner of the
 * screen" behavior actually shows up -- see JobRow for what drives both.
 *
 * Always wrapped in a fixed w-8 h-8 slot: the parent stack is a `fixed`, edge-anchored
 * flex-col with no explicit width/height, so if a row's own box grew in flow (compact icon
 * -> wider/taller pill) the whole stack would reflow and every sibling icon would visibly
 * shift, even ones that never changed state. The expanded pill is positioned absolutely
 * over the slot instead, so it can grow without ever touching the slot's box size. */
function JobIndicator({
  label,
  variant,
  compact,
  onMouseEnter,
  onMouseLeave,
}: {
  label: string
  variant: 'running' | 'done'
  compact: boolean
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}) {
  const Icon = variant === 'running' ? Loader2 : CheckCircle2
  const iconClassName = variant === 'running' ? 'animate-spin' : 'text-emerald-500'

  if (compact) {
    return (
      <div className="relative w-8 h-8" data-testid="job-slot">
        <div
          className="flex items-center justify-center w-8 h-8 rounded-md bg-[var(--c-surface)] border border-[var(--c-border)] shadow-float"
          role="status"
          aria-busy="true"
          aria-label={label}
          title={label}
          onMouseEnter={onMouseEnter}
        >
          <Icon size={14} className={iconClassName} aria-hidden />
        </div>
      </div>
    )
  }

  return (
    <div className="relative w-8 h-8" data-testid="job-slot">
      <div
        className="absolute top-1/2 right-0 -translate-y-1/2 flex items-center gap-2 rounded-lg bg-[var(--c-surface)] border border-[var(--c-border)] px-3 py-2 text-sm text-[var(--c-text)] shadow-float whitespace-nowrap"
        role="status"
        aria-busy="true"
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
      >
        <Icon size={14} className={`shrink-0 ${iconClassName}`} aria-hidden />
        <span>{label}</span>
      </div>
    </div>
  )
}

/** Expands for COLLAPSE_DELAY_MS when `active` turns true (long enough to read), then collapses
 * to an icon-only badge -- hover to re-read the label -- so a long-running job stops covering
 * the corner of the screen. When `active` goes back to false it flashes a static checkmark, in
 * whichever shape (pill or icon) it already had, for FINISH_FLASH_MS before disappearing, so
 * completion doesn't read as an abrupt vanish. Always mounted by the parent (never conditionally
 * rendered) -- that's what makes the post-completion flash possible: it needs to keep rendering
 * for a beat after `active` is already false. */
function JobRow({ active, label }: { active: boolean; label: string }) {
  const [collapsed, setCollapsed] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [finishing, setFinishing] = useState(false)
  const prevActiveRef = useRef(active)

  useEffect(() => {
    const wasActive = prevActiveRef.current
    prevActiveRef.current = active
    if (active && !wasActive) {
      setCollapsed(false)
      setHovered(false)
      setFinishing(false)
    } else if (!active && wasActive) {
      setFinishing(true)
    }
  }, [active])

  useEffect(() => {
    if (!active) return
    const timer = setTimeout(() => setCollapsed(true), COLLAPSE_DELAY_MS)
    return () => clearTimeout(timer)
  }, [active])

  useEffect(() => {
    if (!finishing) return
    const timer = setTimeout(() => setFinishing(false), FINISH_FLASH_MS)
    return () => clearTimeout(timer)
  }, [finishing])

  if (!active && !finishing) return null

  if (finishing) {
    return <JobIndicator label={label} variant="done" compact={collapsed} />
  }

  const compact = collapsed && !hovered
  return (
    <JobIndicator
      label={label}
      variant="running"
      compact={compact}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    />
  )
}

/** Persistent bottom-right indicator for long-running background jobs (skeleton review,
 * timeline archive cascade, world quality review) -- deliberately
 * generic (no chapter/detail): the user only needs to know "is something still running". Each
 * row auto-collapses to an icon after a few seconds; see JobRow for the expand/collapse
 * lifecycle. */
export default function BackgroundJobToast() {
  const novelId = useActiveNovelId()
  const { skeletonReviewActive, timelineCascadeActive, worldReviewActive } =
    useSelector(selectBackgroundJobs(novelId))

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      <JobRow active={skeletonReviewActive} label="章节审查中…" />
      <JobRow active={timelineCascadeActive} label="角色档案推演中…" />
      <JobRow active={worldReviewActive} label="世界观审查中…" />
    </div>
  )
}
