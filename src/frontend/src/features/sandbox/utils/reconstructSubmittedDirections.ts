import type { Round } from '@/features/sandbox/hooks/useStorySandbox'

/** Parse top-level markdown list lines from a director instruction. */
export function parseInstructionListItems(instruction: string): string[] {
  const items: string[] = []
  for (const line of instruction.split('\n')) {
    const m = line.match(/^\s*-\s+(.+)$/)
    if (m) items.push(m[1].trim())
  }
  return items
}

/** When checkpoint omitted submitted_directions, infer from the next round's instruction. */
export function inferSubmittedDirections(rounds: Round[]): Round[] {
  return rounds.map((r, i) => {
    if (r.submittedDirections?.length) return r
    if (i >= rounds.length - 1 || r.suggestions.length === 0) return r
    const picked = parseInstructionListItems(rounds[i + 1].instruction)
      .filter((d) => r.suggestions.includes(d))
    if (picked.length === 0) return r
    return { ...r, submittedDirections: picked }
  })
}
