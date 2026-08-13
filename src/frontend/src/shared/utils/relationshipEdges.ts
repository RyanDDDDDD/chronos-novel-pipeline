import type { RelationshipEdge, RelationshipGraph } from '@/shared/types'

export interface CharacterRelationship {
  other: string
  direction: 'from' | 'to'
  edge: RelationshipEdge
}

/** Pure filter: every edge touching `name`, from either side. No IO -- callers fetch the graph
 * once (useRelationshipGraph) and pass it down to each character card. */
export function relationshipsForCharacter(
  graph: RelationshipGraph | undefined,
  name: string,
): CharacterRelationship[] {
  if (!graph || !name) return []
  const out: CharacterRelationship[] = []
  for (const edge of Object.values(graph.edges ?? {})) {
    if (edge.from === name) out.push({ other: edge.to, direction: 'from', edge })
    else if (edge.to === name) out.push({ other: edge.from, direction: 'to', edge })
  }
  return out
}
