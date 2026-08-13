import type { SandboxMemoryEntry } from '@/shared/types'

export function memorySearchText(e: SandboxMemoryEntry): string {
  return [e.summary, e.location, e.time, ...e.characters, ...e.entities].join(' ').toLowerCase()
}

/** Mirrors recall.py::_format_recall_line's header-bits formatting (chapter/time/location),
 * minus the characters trailer (rendered as its own line by the list item / card instead). */
export function memoryMetaLine(e: SandboxMemoryEntry): string {
  const bits = [`第${e.chapter}章`]
  if (e.time) bits.push(e.time)
  if (e.location) bits.push(`于${e.location}`)
  return bits.join('，')
}

/** One line of manually-recalled memory context, formatted for injection into the director's
 * instruction text -- tagged so it reads distinctly from the user's own freeform text and from
 * selected plot directions. Mirrors recall.py::_format_recall_line's shape (same archived-memory
 * content, just hand-picked instead of auto-injected via a separate prompt section). */
export function formatRecalledMemoryLine(e: SandboxMemoryEntry): string {
  const charSuffix = e.characters.length > 0 ? `（人物：${e.characters.join('、')}）` : ''
  return `[回忆] ${memoryMetaLine(e)}：${e.summary}${charSuffix}`
}
