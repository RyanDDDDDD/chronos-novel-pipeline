import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, waitFor, within, cleanup } from '@testing-library/react'
import { renderWithClient } from '@/test/renderWithClient'
import ImageGenNodeParamsPanel from '@/features/pipeline/components/ImageGenNodeParamsPanel'

vi.mock('@/features/pipeline/utils/authorLoopDialogueConfig', () => ({
  fetchDialogueConfig: vi.fn(),
  putDialogueConfig: vi.fn(),
}))
vi.mock('@/features/pipeline/queries/modelRegistry', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/pipeline/queries/modelRegistry')>()
  return { ...actual, useImageGenModelRegistry: vi.fn() }
})
vi.mock('@/features/pipeline/queries/artStylePresets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/pipeline/queries/artStylePresets')>()
  return { ...actual, useArtStylePresets: vi.fn() }
})

import { putDialogueConfig, fetchDialogueConfig } from '@/features/pipeline/utils/authorLoopDialogueConfig'
import { useImageGenModelRegistry } from '@/features/pipeline/queries/modelRegistry'
import { useArtStylePresets } from '@/features/pipeline/queries/artStylePresets'

const MOCK_DIALOGUE_STATE = {
  config: {
    target_words: 3000,
    disabled_buildtime_review_hooks: [] as string[],
    disabled_runtime_review_hooks: [] as string[],
    disabled_setup_review_hooks: [] as string[],
    llm_params: {},
    sandbox_llm_params: {},
    import_llm_params: {},
    auto_build_character_count: 5,
    auto_build_chapter_count: 3,
    chat_identity: '',
    recall_cooldown_turns: 10,
    recall_top_k: 5,
    portrait_style_prompt: '',
    portrait_negative_prompt: '',
    portrait_style_preset_id: 'anime',
  },
  default_identity: '',
  buildtime_review_hooks: [],
  runtime_review_hooks: [],
  setup_review_hooks: [],
}

const DEFAULT_PRESETS = {
  data: [
    { id: 'anime', label: '日系动漫', previewUrl: '/art-style-presets/anime.jpg' },
    { id: 'cyberpunk', label: '赛博朋克', previewUrl: '/art-style-presets/cyberpunk.jpg' },
  ],
} as never

describe('ImageGenNodeParamsPanel', () => {
  beforeEach(() => {
    vi.mocked(fetchDialogueConfig).mockResolvedValue(MOCK_DIALOGUE_STATE)
    vi.mocked(useArtStylePresets).mockReturnValue(DEFAULT_PRESETS)
  })

  afterEach(() => {
    cleanup()
  })

  it('lets the user pick an image-gen model and saves it', async () => {
    vi.mocked(useImageGenModelRegistry).mockReturnValue({
      data: { customModels: [{ id: 'img-1', label: '我的Novita', model: 'flux-1' }] },
    } as never)

    renderWithClient(
      <ImageGenNodeParamsPanel
        nodeIds={['character_portrait']}
        labels={{ character_portrait: '立绘生成' }}
        selectedNodeId="character_portrait"
        novelId="default"
      />,
      {
        seedDialogueConfig: true,
      },
    )

    const input = await screen.findByLabelText('立绘生成-model-ref')
    const group = input.closest('[data-slot="input-group"]') as HTMLElement
    fireEvent.click(within(group).getAllByRole('button')[0])
    fireEvent.click(await screen.findByRole('option', { name: '我的Novita' }))

    await waitFor(() => {
      expect(putDialogueConfig).toHaveBeenCalledWith('default', {
        dialogue: { import_llm_params: { character_portrait: { model_ref: 'img-1' } } },
      })
    })
  })

  it('writes the model_ref into sandbox_llm_params when configKey says so', async () => {
    vi.mocked(useImageGenModelRegistry).mockReturnValue({
      data: { customModels: [{ id: 'nai-1', label: '我的NovelAI', model: 'nai-diffusion-4-5-full' }] },
    } as never)

    renderWithClient(
      <ImageGenNodeParamsPanel
        nodeIds={['scene_image']}
        labels={{ scene_image: '场景生图' }}
        configKey="sandbox_llm_params"
        selectedNodeId="scene_image"
        novelId="default"
      />,
      { seedDialogueConfig: true },
    )

    const input = await screen.findByLabelText('场景生图-model-ref')
    const group = input.closest('[data-slot="input-group"]') as HTMLElement
    fireEvent.click(within(group).getAllByRole('button')[0])
    fireEvent.click(await screen.findByRole('option', { name: '我的NovelAI' }))

    await waitFor(() => {
      expect(putDialogueConfig).toHaveBeenCalledWith('default', {
        dialogue: { sandbox_llm_params: { scene_image: { model_ref: 'nai-1' } } },
      })
    })
  })

  it('returns null when the selected node is not in nodeIds', () => {
    vi.mocked(useImageGenModelRegistry).mockReturnValue({ data: { customModels: [] } } as never)
    const { container } = renderWithClient(
      <ImageGenNodeParamsPanel nodeIds={['character_portrait']} labels={{}} selectedNodeId="director" novelId="default" />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('lets the user edit and save the fixed style/negative prompts', async () => {
    vi.mocked(useImageGenModelRegistry).mockReturnValue({ data: { customModels: [] } } as never)

    renderWithClient(
      <ImageGenNodeParamsPanel
        nodeIds={['character_portrait']}
        labels={{ character_portrait: '立绘生成' }}
        selectedNodeId="character_portrait"
        novelId="default"
      />,
      { seedDialogueConfig: true },
    )

    const styleInput = await screen.findByLabelText('立绘画风（正向）')
    fireEvent.change(styleInput, { target: { value: 'watercolor style' } })
    fireEvent.blur(styleInput)

    await waitFor(() => {
      expect(putDialogueConfig).toHaveBeenCalledWith('default', {
        dialogue: { portrait_style_prompt: 'watercolor style' },
      })
    })

    const negativeInput = await screen.findByLabelText('立绘负面词')
    fireEvent.change(negativeInput, { target: { value: 'no watermark' } })
    fireEvent.blur(negativeInput)

    await waitFor(() => {
      expect(putDialogueConfig).toHaveBeenCalledWith('default', {
        dialogue: { portrait_negative_prompt: 'no watermark' },
      })
    })
  })

  it('renders the preset gallery, highlights the current selection, and saves on click', async () => {
    vi.mocked(useImageGenModelRegistry).mockReturnValue({ data: { customModels: [] } } as never)
    vi.mocked(useArtStylePresets).mockReturnValue({
      data: [
        { id: 'anime', label: '日系动漫', previewUrl: '/art-style-presets/anime.jpg' },
        { id: 'cyberpunk', label: '赛博朋克', previewUrl: '/art-style-presets/cyberpunk.jpg' },
      ],
    } as never)

    renderWithClient(
      <ImageGenNodeParamsPanel
        nodeIds={['character_portrait']}
        labels={{ character_portrait: '立绘生成' }}
        selectedNodeId="character_portrait"
        novelId="default"
      />,
      { seedDialogueConfig: true },
    )

    const animeCard = await screen.findByRole('button', { name: '日系动漫' })
    expect(animeCard.getAttribute('aria-pressed')).toBe('true')

    const cyberpunkCard = await screen.findByRole('button', { name: '赛博朋克' })
    expect(cyberpunkCard.getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(cyberpunkCard)

    await waitFor(() => {
      expect(putDialogueConfig).toHaveBeenCalledWith('default', {
        dialogue: { portrait_style_preset_id: 'cyberpunk' },
      })
    })
  })

  it('shows an enlarged preview when a preset card is hovered/focused', async () => {
    vi.mocked(useImageGenModelRegistry).mockReturnValue({ data: { customModels: [] } } as never)

    renderWithClient(
      <ImageGenNodeParamsPanel
        nodeIds={['character_portrait']}
        labels={{ character_portrait: '立绘生成' }}
        selectedNodeId="character_portrait"
        novelId="default"
      />,
      { seedDialogueConfig: true },
    )

    const cyberpunkCard = await screen.findByRole('button', { name: '赛博朋克' })
    expect(screen.queryAllByAltText('赛博朋克').length).toBe(0)

    fireEvent.focus(cyberpunkCard)

    await waitFor(() => {
      expect(screen.getByAltText('赛博朋克')).toBeTruthy()
    }, { timeout: 1000 })

    fireEvent.blur(cyberpunkCard)

    await waitFor(() => {
      expect(screen.queryAllByAltText('赛博朋克').length).toBe(0)
    }, { timeout: 1000 })
  })
})
