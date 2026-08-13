import type { CharacterArchive, RelationshipGraph, RenderedSlider } from '@/shared/types'
import { formatGenderLabel } from '@/shared/utils/characterFieldLabels'
import { appendRelationshipsMarkdown } from '@/shared/utils/characterRelationshipsMarkdown'

function joinTags(items: string[] | undefined): string {
  return (items ?? []).filter(Boolean).join('、') || '（无）'
}

function isSliderLevelText(v: unknown): v is { level: number; text: string } {
  return v != null && typeof v === 'object' && 'level' in v && 'text' in v
}

function normalizeRenderedSlider(slider: RenderedSlider): { level: number | string; text: string } {
  if (isSliderLevelText(slider.value)) {
    return { level: slider.value.level, text: slider.value.text }
  }
  return { level: slider.value, text: slider.label }
}

function renderAnchorValue(v: unknown): string {
  if (v == null) return ''
  if (Array.isArray(v)) return v.map(renderAnchorValue).join('、')
  if (isSliderLevelText(v)) return `${v.text}（Lv.${v.level}）`
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function renderRefPool(v: string | string[] | Record<string, string[]> | undefined): string {
  if (!v) return ''
  if (typeof v === 'string') return v
  if (Array.isArray(v)) return v.join('、')
  return Object.entries(v)
    .filter(([, terms]) => terms && terms.length > 0)
    .map(([bucket, terms]) => (bucket === '_default' ? terms.join('、') : `对${bucket}：${terms.join('、')}`))
    .join('；')
}

/** Read-only markdown snapshot of a per-chapter CharacterArchive (same section layout as cast cards). */
export function buildCharacterArchiveMarkdown(
  char: CharacterArchive,
  relationshipGraph?: RelationshipGraph,
): string {
  const lines: string[] = []
  lines.push(`# ${char.name}`)

  const meta: string[] = []
  if (char.role) meta.push(`**角色类型**：${char.role}`)
  if (char.location) meta.push(`**地点**：${char.location}`)
  if (char.gender) meta.push(`**性别**：${formatGenderLabel(char.gender)}`)
  if (meta.length) lines.push('', meta.join('  \n'))

  if (char.identity_background) lines.push('', `## 身份背景`, '', char.identity_background)
  if (char.personality) lines.push('', `## 性格`, '', char.personality)

  const anchors = Object.entries(char.causal_anchors ?? {}).filter(
    ([, v]) => v != null && renderAnchorValue(v) !== '',
  )
  if (anchors.length) {
    lines.push('', '## 因果锚点', '')
    lines.push(anchors.map(([k, v]) => `- **${k}**：${renderAnchorValue(v)}`).join('\n'))
  }

  const sliderEntries = Object.entries(char.sliders ?? {})
  if (sliderEntries.length) {
    lines.push('', '## 成长轴')
    for (const [axis, slider] of sliderEntries) {
      const { level, text } = normalizeRenderedSlider(slider)
      lines.push('', `### ${axis}${level !== '' ? ` · Lv.${level}` : ''}`)
      if (text) lines.push('', text)
    }
  }

  const physique = Object.entries(char.physique ?? {}).filter(([, v]) => v?.trim())
  if (physique.length) {
    lines.push('', '## 体格', '')
    lines.push(physique.map(([k, v]) => `- **${k}**：${v}`).join('\n'))
  }

  if (char.hobbies?.length) lines.push('', `## 爱好`, '', joinTags(char.hobbies))
  if (char.verbal_tic) lines.push('', `## 口癖`, '', char.verbal_tic)

  const addressText = renderRefPool(char.address_ref)
  const selfText = renderRefPool(char.self_ref)
  if (addressText || selfText) {
    lines.push('', '## 称呼', '')
    if (addressText) lines.push(`- **称呼他人**：${addressText}`)
    if (selfText) lines.push(`- **自称**：${selfText}`)
  }

  const tp = char.thought_process
  if (tp && (tp.delta || tp.escalation)) {
    lines.push('', '## 内心活动', '')
    if (tp.delta) lines.push(`- **delta**：${tp.delta}`)
    if (tp.escalation) lines.push(`- **escalation**：${tp.escalation}`)
  }

  appendRelationshipsMarkdown(lines, char.name, relationshipGraph)

  return lines.join('\n').trim()
}
