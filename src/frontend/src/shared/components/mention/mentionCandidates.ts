export interface MentionQuery {
  start: number
  end: number
  query: string
}

/** 光标是否处于一个 "@xxx" 待补全片段中：从 cursor 往回找最近的 "@"，中途遇到
 * 空白/换行则视为不在片段内。找不到返回 null。 */
export function findMentionQuery(value: string, cursor: number): MentionQuery | null {
  if (cursor < 0 || cursor > value.length) return null
  let start = cursor
  while (start > 0) {
    const ch = value[start - 1]
    if (ch === '@') break
    if (/\s/.test(ch)) return null
    start -= 1
  }
  if (start === 0 || value[start - 1] !== '@') return null
  return { start: start - 1, end: cursor, query: value.slice(start, cursor) }
}

export interface MentionCandidate {
  name: string
  type: 'character' | 'setting'
}

/** 候选名单按 name 子串过滤；query 为空返回全部。 */
export function filterMentionCandidates(candidates: MentionCandidate[], query: string): MentionCandidate[] {
  if (!query) return candidates
  return candidates.filter((c) => c.name.includes(query))
}

export interface MentionApplyResult {
  value: string
  cursor: number
}

/** 用选中的角色名替换 [start,end) 片段为 "@全名 "，返回新文本 + 新光标位置。 */
export function applyMentionSelection(
  value: string, start: number, end: number, name: string,
): MentionApplyResult {
  const inserted = `@${name} `
  let endPos = end
  // Consume trailing space to avoid double space
  if (endPos < value.length && value[endPos] === ' ') {
    endPos += 1
  }
  const nextValue = value.slice(0, start) + inserted + value.slice(endPos)
  return { value: nextValue, cursor: start + inserted.length }
}

/** 对全文做子串匹配，返回命中的已知角色名（保持 names 顺序）。 */
export function detectRecognizedNames(text: string, names: string[]): string[] {
  if (!text) return []
  return names.filter((name) => name.length > 0 && text.includes(name))
}
