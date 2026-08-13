export const SUBSYSTEM_META: Record<string, { label: string; accent: string }> = {
  author_loop: { label: '主笔', accent: 'bg-[var(--c-tag-violet-bg)] text-[var(--c-tag-violet-text)] ring-[var(--c-tag-violet-border)]' },
  archive: { label: '角色档案', accent: 'bg-sky-100 text-sky-700 ring-sky-200' },
  setup: { label: '设定', accent: 'bg-amber-100 text-amber-800 ring-amber-200' },
  story_sandbox: { label: '沙盒试写', accent: 'bg-rose-100 text-rose-700 ring-rose-200' },
}

export function subsystemLabel(name: string): string {
  return SUBSYSTEM_META[name]?.label ?? name
}

export function subsystemAccent(name: string): string {
  return SUBSYSTEM_META[name]?.accent ?? 'bg-slate-100 text-slate-700 ring-slate-200'
}

/** Numeric ledger keys render as chapter labels; opaque keys stay as-is. */
export function formatChapterKey(key: string): string {
  const trimmed = key.trim()
  if (/^\d+$/.test(trimmed)) return `第 ${Number(trimmed)} 章`
  return trimmed
}
