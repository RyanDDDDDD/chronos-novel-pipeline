import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithClient'
import AttachmentsTab from '@/features/setup/components/AttachmentsTab'

vi.mock('@/shared/utils/setup', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/utils/setup')>()
  return {
    ...actual,
    fetchAttachmentLibrary: vi.fn(),
    fetchAttachmentParsedContent: vi.fn(),
  }
})

import { fetchAttachmentLibrary, fetchAttachmentParsedContent } from '@/shared/utils/setup'

beforeEach(() => {
  cleanup()
  vi.mocked(fetchAttachmentLibrary).mockResolvedValue([
    {
      attachment_id: 'img1',
      filename: 'page.jpg',
      kind: 'image',
      size_bytes: 1024,
      uploaded_at: '2026-01-01T00:00:00Z',
      has_description: true,
    },
  ])
  vi.mocked(fetchAttachmentParsedContent).mockResolvedValue({
    attachment_id: 'img1',
    filename: 'page.jpg',
    kind: 'image',
    content: '城门口的剑士',
    has_content: true,
  })
})

describe('AttachmentsTab', () => {
  it('lists attachments and shows parsed content for the selected item', async () => {
    renderWithProviders(<AttachmentsTab />)
    await waitFor(() => expect(screen.getAllByText('page.jpg').length).toBeGreaterThan(0))
    await waitFor(() => expect(screen.getByText('城门口的剑士')).toBeTruthy())
  })

  it('shows empty state when there are no attachments', async () => {
    vi.mocked(fetchAttachmentLibrary).mockResolvedValue([])
    renderWithProviders(<AttachmentsTab />)
    await waitFor(() => expect(screen.getByText(/尚无已保存的附件/)).toBeTruthy())
  })

  it('filters to images only', async () => {
    vi.mocked(fetchAttachmentLibrary).mockResolvedValue([
      {
        attachment_id: 'img1',
        filename: 'page.jpg',
        kind: 'image',
        size_bytes: 1024,
        uploaded_at: '',
        has_description: false,
      },
      {
        attachment_id: 'txt1',
        filename: 'notes.txt',
        kind: 'text',
        size_bytes: 64,
        uploaded_at: '',
        has_description: false,
      },
    ])
    renderWithProviders(<AttachmentsTab />)
    await waitFor(() => expect(screen.getByText('notes.txt')).toBeTruthy())
    await userEvent.click(screen.getByRole('button', { name: '图片' }))
    expect(screen.queryByText('notes.txt')).toBeNull()
    expect(screen.getAllByText('page.jpg').length).toBeGreaterThan(0)
  })
})
