import React from 'react'
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CharacterCard from '@/shared/components/CharacterCard'
import type { CharacterArchive } from '@/shared/types'

const archive: CharacterArchive = {
  name: '甲', role: '同质堕落型', causal_anchors: {},
  sliders: { 侵蚀度: { value: 1, label: '动摇' } },
  physique: { horns: '有一对小角' },
  personality: '外冷内热',
}

afterEach(() => cleanup())

describe('CharacterCard highlight', () => {
  it('applies a highlight class to a highlighted scalar field heading', () => {
    render(
      <CharacterCard
        character={archive} isOpen onToggle={() => {}}
        highlightedFields={new Set(['personality'])}
      />,
    )
    const heading = screen.getByRole('heading', { name: '性格' })
    expect(heading.className).toContain('ring-rose-300')
  })

  it('applies a highlight class only to the matching slider axis', () => {
    render(
      <CharacterCard
        character={archive} isOpen onToggle={() => {}}
        highlightedFields={new Set(['sliders:侵蚀度'])}
      />,
    )
    const heading = screen.getByRole('heading', { name: /侵蚀度/ })
    expect(heading.className).toContain('ring-rose-300')
  })

  it('renders with no highlight classes when highlightedFields is omitted', () => {
    render(<CharacterCard character={archive} isOpen onToggle={() => {}} />)
    const heading = screen.getByRole('heading', { name: '性格' })
    expect(heading.className).not.toContain('ring-rose-300')
  })
})

const baseCharacter: CharacterArchive = {
  name: '甲', role: 'protagonist', causal_anchors: {},
} as CharacterArchive

describe('CharacterCard portrait thumbnail', () => {
  it('renders a thumbnail image when hasPortrait is true', () => {
    const { container } = render(<CharacterCard character={baseCharacter} isOpen={false} onToggle={() => {}} hasPortrait />)
    const img = container.querySelector('img')
    expect(img).not.toBeNull()
    expect(img?.getAttribute('src')).toBe('/api/character-portrait/%E7%94%B2/file?v=x')
  })

  it('renders no image when hasPortrait is false or omitted', () => {
    const { container } = render(<CharacterCard character={baseCharacter} isOpen={false} onToggle={() => {}} />)
    expect(container.querySelector('img')).toBeNull()
  })

  it('crops the header thumbnail from the top so the face survives', () => {
    const { container } = render(<CharacterCard character={baseCharacter} isOpen={false} onToggle={() => {}} hasPortrait />)
    expect(container.querySelector('img')?.className).toContain('object-top')
  })
})

describe('CharacterCard expanded portrait', () => {
  it('shows a full portrait column when expanded with showExpandedPortrait', () => {
    render(
      <CharacterCard
        character={baseCharacter} isOpen onToggle={() => {}} hasPortrait showExpandedPortrait
      />,
    )
    const trigger = screen.getByRole('button', { name: '查看甲立绘大图' })
    const img = trigger.querySelector('img')
    expect(img?.getAttribute('src')).toBe('/api/character-portrait/%E7%94%B2/file?v=x')
    expect(img?.className).toContain('object-contain')
  })

  it('opens a zoom overlay when the portrait column is clicked', async () => {
    render(
      <CharacterCard
        character={baseCharacter} isOpen onToggle={() => {}} hasPortrait showExpandedPortrait
      />,
    )
    expect(screen.queryByRole('dialog')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '查看甲立绘大图' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog.querySelector('img')?.getAttribute('alt')).toBe('甲立绘')
  })

  it('omits the full portrait column without showExpandedPortrait', () => {
    render(<CharacterCard character={baseCharacter} isOpen onToggle={() => {}} hasPortrait />)
    expect(screen.queryByRole('button', { name: '查看甲立绘大图' })).toBeNull()
  })
})
