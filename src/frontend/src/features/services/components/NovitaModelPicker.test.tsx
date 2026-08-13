import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { renderWithClient } from '@/test/renderWithClient'
import NovitaModelPicker from '@/features/services/components/NovitaModelPicker'

vi.mock('@/features/services/queries/novitaModelCatalog', () => ({
  useNovitaModelCatalog: vi.fn(),
}))

import { useNovitaModelCatalog } from '@/features/services/queries/novitaModelCatalog'

afterEach(() => {
  cleanup()
})

describe('NovitaModelPicker', () => {
  it('renders a radio list when models are cached', async () => {
    vi.mocked(useNovitaModelCatalog).mockReturnValue({
      data: { models: ['a.safetensors', 'b.safetensors'], baseModels: {} },
    } as never)

    renderWithClient(
      <NovitaModelPicker value="a.safetensors" onChange={vi.fn()} />,
    )

    expect(await screen.findByText('a.safetensors')).toBeTruthy()
    expect(screen.queryByLabelText('模型 ID')).toBeNull()
  })

  it('falls back to a manual input when the cache is empty', async () => {
    vi.mocked(useNovitaModelCatalog).mockReturnValue({ data: { models: [], baseModels: {} } } as never)

    renderWithClient(
      <NovitaModelPicker value="" onChange={vi.fn()} />,
    )

    expect(await screen.findByLabelText('模型 ID')).toBeTruthy()
  })

  it('calls onChange with the sd_name and base_model when a model is selected', async () => {
    const onChange = vi.fn()
    vi.mocked(useNovitaModelCatalog).mockReturnValue({
      data: { models: ['a.safetensors'], baseModels: { 'a.safetensors': 'Pony' } },
    } as never)

    renderWithClient(
      <NovitaModelPicker value="" onChange={onChange} />,
    )

    fireEvent.click(await screen.findByText('a.safetensors'))
    expect(onChange).toHaveBeenCalledWith('a.safetensors', 'Pony')
  })

  it('calls onChange with a null base_model when the selection has no cached mapping', async () => {
    const onChange = vi.fn()
    vi.mocked(useNovitaModelCatalog).mockReturnValue({
      data: { models: ['a.safetensors'], baseModels: {} },
    } as never)

    renderWithClient(
      <NovitaModelPicker value="" onChange={onChange} />,
    )

    fireEvent.click(await screen.findByText('a.safetensors'))
    expect(onChange).toHaveBeenCalledWith('a.safetensors', null)
  })

  it('manual input fallback calls onChange with a null base_model', async () => {
    const onChange = vi.fn()
    vi.mocked(useNovitaModelCatalog).mockReturnValue({ data: { models: [], baseModels: {} } } as never)

    renderWithClient(
      <NovitaModelPicker value="" onChange={onChange} />,
    )

    fireEvent.change(await screen.findByLabelText('模型 ID'), { target: { value: 'manual-name' } })
    expect(onChange).toHaveBeenCalledWith('manual-name', null)
  })

  it('calls the refresh endpoint and shows a toast when search misses', async () => {
    vi.mocked(useNovitaModelCatalog).mockReturnValue({
      data: { models: ['a.safetensors'], baseModels: {} },
    } as never)
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ scheduled: true }), { status: 200 }),
    )

    renderWithClient(
      <NovitaModelPicker value="" onChange={vi.fn()} />,
    )

    fireEvent.change(await screen.findByLabelText('搜索模型'), { target: { value: 'zzz-no-match' } })

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith('/api/image-gen/novita-models/refresh', { method: 'POST' })
    }, { timeout: 1000 })

    fetchSpy.mockRestore()
  })
})
