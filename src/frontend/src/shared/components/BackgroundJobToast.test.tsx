import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, screen, act, fireEvent, render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Provider } from 'react-redux'
import { buildTestStore } from '@/test/renderWithClient'
import { TestProviders } from '@/test/testProviders'
import { wsEventReceived } from '@/shared/store/wsActions'
import { renderWithProviders } from '@/test/renderWithClient'
import BackgroundJobToast from '@/shared/components/BackgroundJobToast'

afterEach(() => cleanup())

describe('BackgroundJobToast', () => {
  it('renders nothing when neither job is active', () => {
    renderWithProviders(<BackgroundJobToast />, {
      activeNovelId: 'novel-A',
      preloadedState: { backgroundJobs: { byNovelId: {} } },
    })
    expect(screen.queryByText(/章节审查中|角色档案推演中|世界观审查中/)).toBeNull()
  })

  it('shows the skeleton review message when active for the current novel', () => {
    renderWithProviders(<BackgroundJobToast />, {
      activeNovelId: 'novel-A',
      preloadedState: {
        backgroundJobs: { byNovelId: { 'novel-A': {
          skeletonReviewActive: true, timelineCascadeActive: false, worldReviewActive: false,
        } } },
      },
    })
    expect(screen.getByText(/章节审查中/)).not.toBeNull()
  })

  it('shows the world review message when active', () => {
    renderWithProviders(<BackgroundJobToast />, {
      activeNovelId: 'novel-A',
      preloadedState: {
        backgroundJobs: { byNovelId: { 'novel-A': {
          skeletonReviewActive: false, timelineCascadeActive: false, worldReviewActive: true,
        } } },
      },
    })
    expect(screen.getByText(/世界观审查中/)).not.toBeNull()
  })

  it('shows both messages when both are active', () => {
    renderWithProviders(<BackgroundJobToast />, {
      activeNovelId: 'novel-A',
      preloadedState: {
        backgroundJobs: { byNovelId: { 'novel-A': {
          skeletonReviewActive: true, timelineCascadeActive: true, worldReviewActive: false,
        } } },
      },
    })
    expect(screen.getByText(/章节审查中/)).not.toBeNull()
    expect(screen.getByText(/角色档案推演中/)).not.toBeNull()
  })

  it('does not show a novel-B-only active job while viewing novel-A', () => {
    renderWithProviders(<BackgroundJobToast />, {
      activeNovelId: 'novel-A',
      preloadedState: {
        backgroundJobs: { byNovelId: { 'novel-B': {
          skeletonReviewActive: true, timelineCascadeActive: false, worldReviewActive: false,
        } } },
      },
    })
    expect(screen.queryByText(/章节审查中/)).toBeNull()
  })
})

describe('auto-collapse after 3s', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('collapses to an icon-only badge after 3 seconds, then expands again on hover', () => {
    renderWithProviders(<BackgroundJobToast />, {
      activeNovelId: 'novel-A',
      preloadedState: {
        backgroundJobs: { byNovelId: { 'novel-A': {
          skeletonReviewActive: true, timelineCascadeActive: false, worldReviewActive: false,
        } } },
      },
    })
    expect(screen.getByText('章节审查中…')).not.toBeNull()

    act(() => {
      vi.advanceTimersByTime(3000)
    })
    expect(screen.queryByText('章节审查中…')).toBeNull()
    const icon = screen.getByRole('status')
    expect(icon.getAttribute('aria-label')).toBe('章节审查中…')

    fireEvent.mouseEnter(icon)
    expect(screen.getByText('章节审查中…')).not.toBeNull()

    fireEvent.mouseLeave(screen.getByRole('status'))
    expect(screen.queryByText('章节审查中…')).toBeNull()
  })

  it('keeps every row in a fixed-size slot so hovering one to expand it cannot resize the shared stack and shift sibling icons', () => {
    renderWithProviders(<BackgroundJobToast />, {
      activeNovelId: 'novel-A',
      preloadedState: {
        backgroundJobs: { byNovelId: { 'novel-A': {
          skeletonReviewActive: true, timelineCascadeActive: false, worldReviewActive: true,
        } } },
      },
    })
    act(() => {
      vi.advanceTimersByTime(3000)
    })
    const slots = screen.getAllByTestId('job-slot')
    expect(slots).toHaveLength(2)
    slots.forEach((slot) => {
      expect(slot.className).toContain('w-8')
      expect(slot.className).toContain('h-8')
    })

    fireEvent.mouseEnter(screen.getAllByRole('status')[0])

    // Hovering must not change the slot's own box size -- only an absolutely
    // positioned overlay is allowed to grow, so the sibling slot (and thus its
    // icon's screen position) never moves.
    slots.forEach((slot) => {
      expect(slot.className).toContain('w-8')
      expect(slot.className).toContain('h-8')
    })
    const expandedPill = screen.getByText('章节审查中…').closest('[role="status"]')
    expect(expandedPill?.className).toContain('absolute')
  })

  it('stays expanded for the first 3 seconds', () => {
    renderWithProviders(<BackgroundJobToast />, {
      activeNovelId: 'novel-A',
      preloadedState: {
        backgroundJobs: { byNovelId: { 'novel-A': {
          skeletonReviewActive: false, timelineCascadeActive: false, worldReviewActive: true,
        } } },
      },
    })
    act(() => {
      vi.advanceTimersByTime(2999)
    })
    expect(screen.getByText('世界观审查中…')).not.toBeNull()
  })
})

function renderWithStore(ui: React.ReactElement, activeNovelId = 'novel-A') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(['novels'], [{ id: activeNovelId, name: 'N', active: true }])
  const store = buildTestStore()
  const utils = render(
    <TestProviders>
      <Provider store={store}>
        <QueryClientProvider client={client}>{ui}</QueryClientProvider>
      </Provider>
    </TestProviders>,
  )
  return { store, ...utils }
}

describe('completion flash', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('flashes a static checkmark in the expanded shape, then removes it, when the job finishes before collapsing', () => {
    const { store } = renderWithStore(<BackgroundJobToast />)
    act(() => {
      store.dispatch(wsEventReceived({ type: 'world_review_started', novel_id: 'novel-A' }))
    })
    act(() => {
      store.dispatch(wsEventReceived({ type: 'world_review_done', novel_id: 'novel-A' }))
    })
    expect(screen.getByText('世界观审查中…')).not.toBeNull()
    const status = screen.getByRole('status')
    expect(status.querySelector('.animate-spin')).toBeNull()

    act(() => {
      vi.advanceTimersByTime(1500)
    })
    expect(screen.queryByText('世界观审查中…')).toBeNull()
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('flashes a static checkmark in the collapsed icon shape when the job finishes after collapsing', () => {
    const { store } = renderWithStore(<BackgroundJobToast />)
    act(() => {
      store.dispatch(wsEventReceived({ type: 'skeleton_review_started', novel_id: 'novel-A' }))
    })
    act(() => {
      vi.advanceTimersByTime(3000)
    })
    act(() => {
      store.dispatch(wsEventReceived({ type: 'skeleton_review_done', novel_id: 'novel-A' }))
    })
    expect(screen.queryByText('章节审查中…')).toBeNull()
    const icon = screen.getByRole('status')
    expect(icon.getAttribute('aria-label')).toBe('章节审查中…')
    expect(icon.querySelector('.animate-spin')).toBeNull()

    act(() => {
      vi.advanceTimersByTime(1500)
    })
    expect(screen.queryByRole('status')).toBeNull()
  })
})
