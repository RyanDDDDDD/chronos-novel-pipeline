import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithClient'
import CastCharacterDetailModal from '@/features/setup/components/CastCharacterDetailModal'
import type { CastCharacter } from '@/shared/types'

describe('CastCharacterDetailModal', () => {
  afterEach(() => {
    cleanup()
  })

  it('defaults to preview and toggles into edit mode', async () => {
    const character = {
      name: '角色甲',
      role: 'submissive',
      gender: 'female',
      identity: '身份句',
      identity_background: '没落贵族',
    } as CastCharacter

    renderWithProviders(
      <CastCharacterDetailModal
        character={character}
        open
        onOpenChange={vi.fn()}
        onSave={vi.fn()}
        customFieldSpecs={[]}
      />,
    )

    expect(await screen.findByText('没落贵族')).toBeTruthy()
    expect(screen.queryByRole('textbox', { name: '编辑角色甲档案' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '编辑' }))
    const editor = await screen.findByRole('textbox', { name: '编辑角色甲档案' }) as HTMLTextAreaElement
    expect(editor.value).toMatch(/## 身份背景/)
    expect(editor.value).toMatch(/没落贵族/)

    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    expect(await screen.findByText('没落贵族')).toBeTruthy()
    expect(screen.queryByRole('textbox', { name: '编辑角色甲档案' })).toBeNull()
  })

  it('parses edits and saves on close', async () => {
    const onSave = vi.fn().mockResolvedValue({
      ok: true,
      character: { name: '角色甲', identity_background: '新背景' },
    })
    const onOpenChange = vi.fn()
    const character = {
      name: '角色甲',
      role: 'submissive',
      gender: 'female',
      identity_background: '旧背景',
    } as CastCharacter

    renderWithProviders(
      <CastCharacterDetailModal
        character={character}
        open
        onOpenChange={onOpenChange}
        onSave={onSave}
        customFieldSpecs={[]}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: '编辑' }))
    const editor = await screen.findByRole('textbox', { name: '编辑角色甲档案' })
    fireEvent.change(editor, { target: { value: editor.value.replace('旧背景', '新背景') } })
    fireEvent.keyDown(document, { key: 'Escape' })

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave.mock.calls[0]?.[1].identity_background).toBe('新背景')
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it('shows a regenerate-portrait button in the header', async () => {
    const character = {
      name: '角色甲',
      role: 'submissive',
      gender: 'female',
      identity_background: '没落贵族',
    } as CastCharacter

    renderWithProviders(
      <CastCharacterDetailModal
        character={character}
        open
        onOpenChange={vi.fn()}
        onSave={vi.fn()}
        customFieldSpecs={[]}
      />,
    )

    expect(await screen.findByRole('button', { name: /重新生成立绘/ })).not.toBeNull()
  })

  it('shows the cached portrait visual tags in preview', async () => {
    const character = {
      name: '角色甲',
      role: 'submissive',
      gender: 'female',
      portrait_visual_tags: '1girl, silver hair, red eyes',
    } as CastCharacter

    renderWithProviders(
      <CastCharacterDetailModal
        character={character}
        open
        onOpenChange={vi.fn()}
        onSave={vi.fn()}
        customFieldSpecs={[]}
      />,
    )

    expect(await screen.findByText('1girl, silver hair, red eyes')).toBeTruthy()
  })

  it('shows a placeholder when portrait visual tags have not been extracted yet', async () => {
    const character = { name: '角色甲', role: 'submissive', gender: 'female' } as CastCharacter

    renderWithProviders(
      <CastCharacterDetailModal
        character={character}
        open
        onOpenChange={vi.fn()}
        onSave={vi.fn()}
        customFieldSpecs={[]}
      />,
    )

    expect(await screen.findByText(/尚未生成，首次生图时自动提取/)).toBeTruthy()
  })

  it('makes the visual tags editable and saves manual edits', async () => {
    const onSave = vi.fn().mockResolvedValue({
      ok: true,
      character: { name: '角色甲' },
    })
    const character = {
      name: '角色甲',
      role: 'submissive',
      gender: 'female',
      portrait_visual_tags: '1girl, silver hair, red eyes',
    } as CastCharacter

    renderWithProviders(
      <CastCharacterDetailModal
        character={character}
        open
        onOpenChange={vi.fn()}
        onSave={onSave}
        customFieldSpecs={[]}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: '编辑' }))
    const editor = await screen.findByRole('textbox', { name: '编辑角色甲档案' }) as HTMLTextAreaElement
    expect(editor.value).toMatch(/## 生图提示词/)
    expect(editor.value).toMatch(/1girl, silver hair, red eyes/)

    fireEvent.change(editor, {
      target: { value: editor.value.replace('1girl, silver hair, red eyes', '1girl, golden hair, blue eyes') },
    })
    fireEvent.keyDown(document, { key: 'Escape' })

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave.mock.calls[0]?.[1].portrait_visual_tags).toBe('1girl, golden hair, blue eyes')
  })
})
