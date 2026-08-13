import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Provider } from 'react-redux'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import React from 'react'
import { buildTestStore } from '@/test/renderWithClient'

vi.mock('@/shared/utils/novels', () => ({
  fetchNovels: vi.fn(async () => [
    { id: 'n1', name: 'N1', active: true },
    { id: 'n2', name: 'N2', active: false },
  ]),
  createNovel: vi.fn(), switchNovel: vi.fn(), renameNovel: vi.fn(), deleteNovel: vi.fn(),
}))
vi.mock('@/features/pipeline/components/PipelineWorkflowConfigView', () => ({ default: () => <div data-testid="author-loop-config" /> }))

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.includes('/api/chapters') ? { chapters: [{ chapter: 1, title: null }] } : {},
  })) as unknown as typeof fetch)
})

import App from './App'

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })
  client.setQueryData(['novels'], [
    { id: 'n1', name: 'N1', active: true },
    { id: 'n2', name: 'N2', active: false },
  ])
  const store = buildTestStore({ sandbox: { busy: true } })
  return render(
    <Provider store={store}>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/novel/n1/pipeline']}>
          <Routes>
            <Route path="/novel/:novelId/*" element={<App />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </Provider>,
  )
}

describe('story-sandbox 流式传输期间小说栏', () => {
  it('sandboxBusy 为 true 时小说栏切换按钮仍可点击', () => {
    renderApp()
    expect((screen.getByText('N2') as HTMLButtonElement).disabled).toBe(false)
  })
})
