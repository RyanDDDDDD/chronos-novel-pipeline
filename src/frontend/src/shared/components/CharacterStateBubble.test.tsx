import React from 'react'
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { CharacterStateBubble } from './CharacterStateBubble'
import { BASELINE_STATE_DERIVE_FIELDS } from '@/shared/utils/characterStateFields'

afterEach(() => {
  cleanup()
})

describe('CharacterStateBubble', () => {
  it('renders nothing when characters is empty', () => {
    const { container } = render(<CharacterStateBubble characters={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders only the non-empty fields, in order', () => {
    render(
      <CharacterStateBubble characters={[{
        name: '甲', psychology: '紧张', posture: '前倾', clothing: '', action: '攥紧衣角', demeanor: '',
      }]} />,
    )
    fireEvent.click(screen.getByText(/🧬 角色状态（推演）/))
    expect(screen.getByText(/心理：紧张/)).toBeTruthy()
    expect(screen.getByText(/体态：前倾/)).toBeTruthy()
    expect(screen.getByText(/动作：攥紧衣角/)).toBeTruthy()
    expect(screen.queryByText(/着装：/)).toBeNull()
    expect(screen.queryByText(/神态：/)).toBeNull()
  })

  it('defaults to collapsed when entry is not set, expanded when entry is true', () => {
    const { rerender } = render(
      <CharacterStateBubble characters={[{ name: '甲', psychology: '紧张' }]} />,
    )
    expect(screen.getByText(/🧬 角色状态（推演）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('closed')
    rerender(
      <CharacterStateBubble characters={[{ name: '甲', psychology: '紧张' }]} entry />,
    )
    expect(screen.getByText(/🧬 角色进入态（初始）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')
  })

  it('forceOpen overrides the entry-based default in both directions', () => {
    const { rerender } = render(
      <CharacterStateBubble characters={[{ name: '甲', psychology: '紧张' }]} forceOpen />,
    )
    expect(screen.getByText(/🧬 角色状态（推演）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('open')
    rerender(
      <CharacterStateBubble characters={[{ name: '甲', psychology: '紧张' }]} entry forceOpen={false} />,
    )
    expect(screen.getByText(/🧬 角色进入态（初始）/).closest('[data-slot="collapsible"]')?.getAttribute('data-state')).toBe('closed')
  })

  it('supports overriding the title', () => {
    render(
      <CharacterStateBubble characters={[{ name: '甲', psychology: '紧张' }]} title="🌱 开场初始状态" />,
    )
    expect(screen.getByText(/🌱 开场初始状态/)).toBeTruthy()
  })

  it('renders scored_desc fields when provided in schema', () => {
    render(
      <CharacterStateBubble
        characters={[{ name: '甲', stress_level: { score: 80, desc: '身体发热' } }]}
        fields={[
          ...BASELINE_STATE_DERIVE_FIELDS,
          { key: 'stress_level', label: '压力值', kind: 'scored_desc' },
        ]}
      />,
    )
    fireEvent.click(screen.getByText(/🧬 角色状态（推演）/))
    expect(screen.getByText(/压力值：80\/100，身体发热/)).toBeTruthy()
  })

  it('joins multiple character names in the summary', () => {
    render(
      <CharacterStateBubble characters={[
        { name: '甲', psychology: '紧张' }, { name: '乙', psychology: '平静' },
      ]} />,
    )
    expect(screen.getByText(/甲、乙/)).toBeTruthy()
  })
})
