/** Structured output of role agent: lines/action intentions/mental activities. When the JSON is not closed in the streaming stage, try to split the fields for display.*/
export interface CharacterPerformance {
  dialogue: string
  intent: string
  psychology: string
  /** true = parsed from JSON stream (including unclosed increments)*/
  fromJson: boolean
}

const JSON_KEYS = ['dialogue', 'intent', 'psychology'] as const

function unescapeJsonString(raw: string): string {
  return raw
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\r')
    .replace(/\\t/g, '\t')
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, '\\')
}

/** 从未闭合的 JSON 流里抠出某 string 字段（支持值还在打字中、缺闭合引号）。 */
function pickStreamingString(raw: string, key: string): string {
  const re = new RegExp(`"${key}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)(?:"|$)`)
  const m = raw.match(re)
  return m ? unescapeJsonString(m[1]) : ''
}

function stripCodeFence(raw: string): string {
  const t = raw.trim()
  const fenced = t.match(/^```(?:json)?\s*([\s\S]*?)(?:```|$)/i)
  return (fenced ? fenced[1] : t).trim()
}

/** 解析角色 JSON 输出；流式未闭合时按 key 增量提取，避免 live 气泡整段裸 JSON。 */
export function parseCharacterPerformance(raw: string): CharacterPerformance | null {
  const text = stripCodeFence(raw)
  if (!text) return null

  // 完整 JSON（定稿或流已闭合）
  if (text.startsWith('{')) {
    try {
      const data = JSON.parse(text) as Record<string, unknown>
      if (data && typeof data === 'object') {
        return {
          dialogue: String(data.dialogue ?? ''),
          intent: String(data.intent ?? ''),
          psychology: String(data.psychology ?? ''),
          fromJson: true,
        }
      }
    } catch {
      // 流式未闭合 → 走增量 key 提取
    }
    const partial: CharacterPerformance = {
      dialogue: pickStreamingString(text, 'dialogue'),
      intent: pickStreamingString(text, 'intent'),
      psychology: pickStreamingString(text, 'psychology'),
      fromJson: true,
    }
    if (partial.dialogue || partial.intent || partial.psychology || JSON_KEYS.some(k => text.includes(`"${k}"`))) {
      return partial
    }
  }

  return null
}

/** segment 定稿：优先用已拆好的字段；text 仍是整段 JSON 时回退解析。 */
export function resolveCharacterSegment(seg: {
  text: string
  intent?: string
  psychology?: string
}): { dialogue: string; intent: string; psychology: string } {
  const hasSplit = Boolean((seg.intent ?? '').trim() || (seg.psychology ?? '').trim())
  if (hasSplit || !seg.text.trim().startsWith('{')) {
    return {
      dialogue: seg.text,
      intent: seg.intent ?? '',
      psychology: seg.psychology ?? '',
    }
  }
  const parsed = parseCharacterPerformance(seg.text)
  if (parsed) {
    return {
      dialogue: parsed.dialogue,
      intent: parsed.intent,
      psychology: parsed.psychology,
    }
  }
  return { dialogue: seg.text, intent: seg.intent ?? '', psychology: seg.psychology ?? '' }
}
