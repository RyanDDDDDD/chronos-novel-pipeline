import type { CastCharacter, CustomFieldSpec } from '@/shared/types'
import { CHARACTER_PROFILE_FIELD_LABELS } from '@/shared/utils/characterFieldLabels'
import { parseGenderLabel } from '@/shared/utils/parseGenderLabel'

const READ_ONLY_SECTIONS = new Set(['关系', '成长轴', '身份'])

export interface ParsedCastCharacterMarkdown {
  given_name?: string
  role?: string
  gender?: string
  race?: string
  identity_background?: string
  personality?: string
  causal_anchors?: Record<string, string>
  physique?: Record<string, string>
  clothing_dna?: {
    signature_outfit?: string
    accessories?: string[]
    color_palette?: string[]
    materials_preference?: string[]
  }
  hobbies?: string[]
  verbal_tic?: string
  portrait_visual_tags?: string
  portrait_identity_tags?: string
  customFields?: Record<string, string>
}

export function parseTagList(raw: string): string[] {
  const value = raw.trim()
  if (!value || value === '（无）') return []
  return value.split('、').map((part) => part.trim()).filter(Boolean)
}

function splitMarkdownSections(markdown: string): {
  title: string
  preamble: string
  sections: Map<string, string>
} {
  const sections = new Map<string, string>()
  const preambleLines: string[] = []
  let title = ''
  let currentHeading: string | null = null
  let currentLines: string[] = []

  const flush = () => {
    if (currentHeading) {
      sections.set(currentHeading, currentLines.join('\n').trim())
      currentLines = []
    }
  }

  for (const line of markdown.split('\n')) {
    if (line.startsWith('# ')) {
      title = line.slice(2).trim()
      continue
    }
    if (line.startsWith('## ')) {
      flush()
      currentHeading = line.slice(3).trim()
      continue
    }
    if (currentHeading) currentLines.push(line)
    else preambleLines.push(line)
  }
  flush()

  return { title, preamble: preambleLines.join('\n').trim(), sections }
}

function parseBulletKeyValues(body: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of body.split('\n')) {
    const match = line.match(/^-\s+\*\*(.+?)\*\*[：:]\s*(.+)$/)
    if (match) out[match[1].trim()] = match[2].trim()
  }
  return out
}

function parseMeta(preamble: string): Pick<ParsedCastCharacterMarkdown, 'role' | 'gender' | 'race'> {
  const out: Pick<ParsedCastCharacterMarkdown, 'role' | 'gender' | 'race'> = {}
  for (const chunk of preamble.split(/\s{2}\n|\n/)) {
    const roleMatch = chunk.match(/^\*\*角色类型\*\*[：:]\s*(.+)$/)
    if (roleMatch) out.role = roleMatch[1].trim()
    const genderMatch = chunk.match(/^\*\*性别\*\*[：:]\s*(.+)$/)
    if (genderMatch) out.gender = parseGenderLabel(genderMatch[1])
    const raceMatch = chunk.match(/^\*\*种族\*\*[：:]\s*(.+)$/)
    if (raceMatch) out.race = raceMatch[1].trim()
  }
  return out
}

function parseTitleGivenName(title: string): string | undefined {
  const match = title.match(/^(.+?)（(.+)）$/)
  return match ? match[2].trim() : undefined
}

function sectionLabelToFieldKey(label: string, customFieldSpecs: CustomFieldSpec[]): string | null {
  for (const [key, sectionLabel] of Object.entries(CHARACTER_PROFILE_FIELD_LABELS)) {
    if (sectionLabel === label) return key
  }
  if (customFieldSpecs.some((spec) => spec.name === label)) return label
  return null
}

function parseClothingDna(body: string): ParsedCastCharacterMarkdown['clothing_dna'] {
  const bullets = parseBulletKeyValues(body)
  return {
    signature_outfit: bullets['招牌常服'] ?? '',
    accessories: parseTagList(bullets['配饰'] ?? ''),
    color_palette: parseTagList(bullets['色系'] ?? ''),
    materials_preference: parseTagList(bullets['材质'] ?? ''),
  }
}

export function parseCastCharacterMarkdown(
  markdown: string,
  options: { customFieldSpecs?: CustomFieldSpec[]; baseline?: CastCharacter } = {},
): ParsedCastCharacterMarkdown {
  const customFieldSpecs = options.customFieldSpecs ?? []
  const { title, preamble, sections } = splitMarkdownSections(markdown)
  const parsed: ParsedCastCharacterMarkdown = {
    ...parseMeta(preamble),
    customFields: {},
  }

  const givenFromTitle = parseTitleGivenName(title)
  if (givenFromTitle) parsed.given_name = givenFromTitle

  for (const [label, body] of sections.entries()) {
    if (READ_ONLY_SECTIONS.has(label)) continue

    if (label === '身份背景') parsed.identity_background = body
    else if (label === '性格') parsed.personality = body
    else if (label === '因果锚点') parsed.causal_anchors = parseBulletKeyValues(body)
    else if (label === '体格') parsed.physique = parseBulletKeyValues(body)
    else if (label === '着装 DNA') parsed.clothing_dna = parseClothingDna(body)
    else if (label === '形象锚定') parsed.portrait_identity_tags = body
    else if (label === '生图提示词') parsed.portrait_visual_tags = body
    else if (label === '爱好') parsed.hobbies = parseTagList(body)
    else if (label === '口癖') parsed.verbal_tic = body
    else {
      const fieldKey = sectionLabelToFieldKey(label, customFieldSpecs)
      if (fieldKey && parsed.customFields) parsed.customFields[fieldKey] = body
    }
  }

  return parsed
}
