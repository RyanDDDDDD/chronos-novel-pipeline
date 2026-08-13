export const NOVEL_SWITCH_LABEL = '正在切换小说…'

/** Full-screen overlay while per-novel agent/chat state is loading after a novel switch. */
export default function NovelSwitchOverlay() {
  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-[color-mix(in_srgb,var(--c-bg-app)_88%,transparent)] backdrop-blur-[2px]"
      role="status"
      aria-live="polite"
      aria-label={NOVEL_SWITCH_LABEL}
    >
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--c-border)] border-t-[var(--c-accent)]" />
      <p className="text-sm text-[var(--c-text-secondary)]">{NOVEL_SWITCH_LABEL}</p>
    </div>
  )
}
