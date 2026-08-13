/** Mirror backend `_locate_fragment`: find `originalText` in markdown prose, disambiguate by
 * `anchorOffset` when it appears more than once. */
export function locateProseFragment(
  prose: string,
  originalText: string,
  anchorOffset: number,
): { start: number; end: number } | null {
  if (!originalText) return null
  const starts: number[] = []
  let idx = prose.indexOf(originalText)
  while (idx !== -1) {
    starts.push(idx)
    idx = prose.indexOf(originalText, idx + 1)
  }
  if (starts.length === 0) return null
  const start = starts.reduce((best, s) => (
    Math.abs(s - anchorOffset) < Math.abs(best - anchorOffset) ? s : best
  ))
  return { start, end: start + originalText.length }
}

/** Split prose for in-place selection-rewrite loading: keep stable head/tail, omit the selected
 * span, and place the loader at the first `\n` after stable text (selection start), falling
 * back to inline at the selection start when no newline follows. */
export function splitProseForSelectionRewriteLoading(
  prose: string,
  originalText: string,
  anchorOffset: number,
): { head: string; tail: string } | null {
  const loc = locateProseFragment(prose, originalText, anchorOffset)
  if (!loc) return null
  const { start, end } = loc
  const nl = prose.indexOf('\n', start)
  let insertAt = nl === -1 ? start : nl + 1
  if (insertAt > end) insertAt = start
  return {
    head: prose.slice(0, insertAt),
    tail: prose.slice(end),
  }
}
