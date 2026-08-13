import React from 'react'
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import RelationshipEdgesSection from '@/shared/components/RelationshipEdgesSection'
import type { CharacterRelationship } from '@/shared/utils/relationshipEdges'

afterEach(cleanup)

describe('RelationshipEdgesSection', () => {
  it('shows a placeholder when there are no relationships', () => {
    render(<RelationshipEdgesSection relationships={[]} />)
    expect(screen.getByText('关系')).toBeTruthy()
    expect(screen.getByText('暂无')).toBeTruthy()
  })

  it('renders each relationship with direction, nature, and ref terms', () => {
    const relationships: CharacterRelationship[] = [
      {
        other: '小明', direction: 'from',
        edge: {
          from: '若曦', to: '小明', nature: '兄妹', relationship_anchor: '',
          from_ref_terms: ['妹妹'], to_ref_terms: ['哥哥'],
        },
      },
    ]
    render(<RelationshipEdgesSection relationships={relationships} />)
    expect(screen.getByText('关系')).toBeTruthy()
    expect(screen.queryByText('暂无')).toBeNull()
    expect(screen.getByText(/小明/).textContent).toBe('→ 小明（兄妹）·妹妹/哥哥')
    expect(screen.getByText('·妹妹/哥哥')).toBeTruthy()
  })
})
