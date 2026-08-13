import type { RelationshipGraph } from '@/shared/types'
import { relationshipsForCharacter } from '@/shared/utils/relationshipEdges'

/** Append a ## 关系 section for one character (shared by cast + archive markdown builders). */
export function appendRelationshipsMarkdown(
  lines: string[],
  characterName: string,
  relationshipGraph?: RelationshipGraph,
): void {
  const relationships = relationshipsForCharacter(relationshipGraph, characterName)
  if (relationships.length === 0) return

  lines.push('## 关系', '')
  for (const { other, direction, edge } of relationships) {
    const terms = [...(edge.from_ref_terms ?? []), ...(edge.to_ref_terms ?? [])]
    const arrow = direction === 'from' ? '→' : '←'
    const termsStr = terms.length > 0 ? ` · ${terms.join('/')}` : ''
    const anchor = edge.relationship_anchor ? ` — ${edge.relationship_anchor}` : ''
    lines.push(`- ${arrow} **${other}**（${edge.nature}）${termsStr}${anchor}`)
  }
}
