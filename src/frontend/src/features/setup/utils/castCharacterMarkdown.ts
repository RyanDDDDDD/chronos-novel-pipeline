import type { CastCharacter, CustomFieldSpec, RelationshipGraph } from '@/shared/types'
import { CHARACTER_PROFILE_FIELD_LABELS, formatGenderLabel } from '@/shared/utils/characterFieldLabels'
import { appendRelationshipsMarkdown } from '@/shared/utils/characterRelationshipsMarkdown'

function joinTags(items: string[] | undefined): string {
  return (items ?? []).filter(Boolean).join('、') || '（无）'
}

function sortSliderLevelEntries(levels: Record<string, string>): [string, string][] {
  return Object.entries(levels).sort(([a], [b]) => {
    const na = Number(a)
    const nb = Number(b)
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb
    return a.localeCompare(b)
  })
}

type SliderValue = string | number | { level: number; text: string; levels?: Record<string, string> }

function renderSliderValue(v: SliderValue): string {
  return typeof v === 'object' && v !== null && 'text' in v ? v.text : String(v)
}

function appendSliderMarkdown(lines: string[], axis: string, value: SliderValue): void {
  const level = typeof value === 'object' && value !== null && 'level' in value ? value.level : null
  const text = renderSliderValue(value)
  const levels =
    typeof value === 'object' && value !== null && 'levels' in value && value.levels
      ? sortSliderLevelEntries(value.levels)
      : null

  lines.push(`### ${axis}${level != null ? ` · Lv.${level}` : ''}`)
  if (text) lines.push('', text)

  if (levels && levels.length > 0) {
    lines.push('')
    for (const [lv, ladderText] of levels) {
      const active = level != null && String(level) === lv
      lines.push(active ? `- **Lv.${lv}：${ladderText}**（当前）` : `- Lv.${lv}：${ladderText}`)
    }
  } else if (level == null) {
    lines.push('', `- ${text}`)
  }
}

export interface BuildCastCharacterMarkdownOptions {
  customFieldSpecs?: CustomFieldSpec[]
  relationshipGraph?: RelationshipGraph
  portraitUrl?: string | null
}

/** Read-only markdown snapshot of a cast character for modal display. */
export function buildCastCharacterMarkdown(
  char: CastCharacter,
  customFieldSpecsOrOptions: CustomFieldSpec[] | BuildCastCharacterMarkdownOptions = [],
  legacyRelationshipGraph?: RelationshipGraph,
): string {
  const options: BuildCastCharacterMarkdownOptions = Array.isArray(customFieldSpecsOrOptions)
    ? { customFieldSpecs: customFieldSpecsOrOptions, relationshipGraph: legacyRelationshipGraph }
    : customFieldSpecsOrOptions
  const customFieldSpecs = options.customFieldSpecs ?? []

  const lines: string[] = []
  const displayName =
    char.given_name && char.given_name !== char.name
      ? `${char.name}（${char.given_name}）`
      : char.name
  lines.push(`# ${displayName}`)

  if (options.portraitUrl) {
    lines.push('', `![${displayName}](${options.portraitUrl})`)
  }

  const meta: string[] = []
  if (char.role) meta.push(`**角色类型**：${char.role}`)
  if (char.gender) meta.push(`**性别**：${formatGenderLabel(char.gender)}`)
  if (char.race) meta.push(`**种族**：${char.race}`)
  if (meta.length) lines.push('', meta.join('  \n'))

  if (char.identity) lines.push('', `## 身份`, '', char.identity)
  if (char.identity_background) lines.push('', `## 身份背景`, '', char.identity_background)
  if (char.personality) lines.push('', `## 性格`, '', char.personality)

  const anchors = Object.entries(char.causal_anchors ?? {}).filter(([, v]) => v?.trim())
  if (anchors.length) {
    lines.push('', '## 因果锚点', '')
    lines.push(anchors.map(([k, v]) => `- **${k}**：${v}`).join('\n'))
  }

  const sliders = Object.entries(char.sliders ?? {})
  if (sliders.length) {
    lines.push('', '## 成长轴')
    for (const [axis, val] of sliders) {
      lines.push('')
      appendSliderMarkdown(lines, axis, val as SliderValue)
    }
  }

  const physique = Object.entries(char.physique ?? {}).filter(([, v]) => v?.trim())
  if (physique.length) {
    lines.push('', '## 体格', '')
    lines.push(physique.map(([k, v]) => `- **${k}**：${v}`).join('\n'))
  }

  const dna = char.clothing_dna
  if (dna) {
    lines.push('', '## 着装 DNA', '')
    if (dna.signature_outfit) lines.push(`- **招牌常服**：${dna.signature_outfit}`)
    lines.push(`- **配饰**：${joinTags(dna.accessories)}`)
    lines.push(`- **色系**：${joinTags(dna.color_palette)}`)
    lines.push(`- **材质**：${joinTags(dna.materials_preference)}`)
  }

  if (char.portrait_identity_tags) lines.push('', `## 形象锚定`, '', char.portrait_identity_tags)
  if (char.portrait_visual_tags) lines.push('', `## 生图提示词`, '', char.portrait_visual_tags)

  if (char.hobbies?.length) lines.push('', `## 爱好`, '', joinTags(char.hobbies))
  if (char.verbal_tic) lines.push('', `## 口癖`, '', char.verbal_tic)

  appendRelationshipsMarkdown(lines, char.given_name || char.name, options.relationshipGraph)

  for (const spec of customFieldSpecs) {
    const value = String((char as unknown as Record<string, unknown>)[spec.name] ?? '').trim()
    if (value) {
      const label = CHARACTER_PROFILE_FIELD_LABELS[spec.name] ?? spec.name
      lines.push('', `## ${label}`, '', value)
    }
  }

  return lines.join('\n').trim()
}
