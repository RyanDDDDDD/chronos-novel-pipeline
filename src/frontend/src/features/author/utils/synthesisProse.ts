/** Synthetic agent structured output: the first line is marked with `# synthesized text`, followed by the text.*/

const SYNTHESIS_HEADER_RE = /^#\s*合成正文\s*\n?/

/** Remove composite title lines from finalized or streaming buffers; do not expose prefixes when markup is still being typed.*/
export function stripSynthesisProse(raw: string): string {
  const text = raw ?? ''
  if (!text) return ''
  const m = text.match(SYNTHESIS_HEADER_RE)
  if (m) return text.slice(m[0].length)
  //Streaming: # Synthetic Text Hide before finishing
  if (/^#\s*/.test(text)) {
    const body = text.replace(/^#\s*/, '')
    if (body === '' || '合成正文'.startsWith(body)) return ''
  }
  return text
}
