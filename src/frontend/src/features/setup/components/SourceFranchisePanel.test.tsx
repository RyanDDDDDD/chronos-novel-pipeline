import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import SourceFranchisePanel from '@/features/setup/components/SourceFranchisePanel'
import { renderWithClient } from '@/test/renderWithClient'

vi.mock('@/shared/utils/novels', () => ({
  getSourceFranchise: vi.fn(),
  setSourceFranchise: vi.fn(),
}))
import { getSourceFranchise, setSourceFranchise } from '@/shared/utils/novels'

beforeEach(() => {
  cleanup()
  vi.mocked(getSourceFranchise).mockResolvedValue('Blue Archive')
  vi.mocked(setSourceFranchise).mockResolvedValue({ ok: true })
})

describe('SourceFranchisePanel', () => {
  it('loads the stored franchise into the input', async () => {
    renderWithClient(<SourceFranchisePanel novelId="default" />)
    await waitFor(() =>
      expect((screen.getByPlaceholderText(/原创小说留空/) as HTMLInputElement).value).toBe('Blue Archive'),
    )
  })

  it('saves the edited value and closes', async () => {
    const onClose = vi.fn()
    renderWithClient(<SourceFranchisePanel novelId="default" onClose={onClose} />)
    const input = screen.getByPlaceholderText(/原创小说留空/) as HTMLInputElement
    await waitFor(() => expect(input.value).toBe('Blue Archive'))

    fireEvent.change(input, { target: { value: 'Genshin Impact' } })
    fireEvent.click(screen.getByText('保存'))

    await waitFor(() => expect(setSourceFranchise).toHaveBeenCalledWith('default', 'Genshin Impact'))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })
})
