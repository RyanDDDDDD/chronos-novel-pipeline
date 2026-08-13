import { describe, expect, it } from 'vitest'
import { relationshipsForCharacter } from './relationshipEdges'
import type { RelationshipGraph } from '@/shared/types'

describe('relationshipsForCharacter', () => {
  const graph: RelationshipGraph = {
    groups: {},
    edges: {
      '小红→小明': {
        from: '小红', to: '小明', nature: '兄妹', relationship_anchor: '',
        from_ref_terms: ['妹妹'], to_ref_terms: ['哥哥'],
      },
      '小明→王五': {
        from: '小明', to: '王五', nature: '师徒', relationship_anchor: '执念',
        from_ref_terms: [], to_ref_terms: ['师傅'],
      },
    },
  }

  it('finds edges where the character is "from"', () => {
    const rel = relationshipsForCharacter(graph, '小红')
    expect(rel).toEqual([{ other: '小明', direction: 'from', edge: graph.edges['小红→小明'] }])
  })

  it('finds edges where the character is "to"', () => {
    const rel = relationshipsForCharacter(graph, '小明')
    expect(rel).toHaveLength(2)
    expect(rel).toContainEqual({ other: '小红', direction: 'to', edge: graph.edges['小红→小明'] })
    expect(rel).toContainEqual({ other: '王五', direction: 'from', edge: graph.edges['小明→王五'] })
  })

  it('returns empty for a character with no edges', () => {
    expect(relationshipsForCharacter(graph, '路人')).toEqual([])
  })

  it('returns empty when graph is undefined', () => {
    expect(relationshipsForCharacter(undefined, '小红')).toEqual([])
  })

  it('returns empty when name is blank', () => {
    expect(relationshipsForCharacter(graph, '')).toEqual([])
  })
})
