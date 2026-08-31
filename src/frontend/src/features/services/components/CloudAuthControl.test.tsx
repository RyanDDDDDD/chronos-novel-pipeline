import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { screen, waitFor, cleanup, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CloudAuthControl from '@/features/services/components/CloudAuthControl'
import { renderWithProviders } from '@/test/renderWithClient'

function mockFetch(status: { logged_in: boolean }) {
  const calls: { url: string; method: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? 'GET' })
      if (url === '/api/auth/status') return { ok: true, json: async () => status }
      return { ok: true, json: async () => ({}) }
    }),
  )
  return calls
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('CloudAuthControl', () => {
  it('shows a login button when logged out and opens the dialog', async () => {
    mockFetch({ logged_in: false })
    renderWithProviders(<CloudAuthControl collapsed={false} />, {
      preloadedState: { cloudAuth: { isLoggedIn: false, lastErrorCode: null } },
    })

    expect(screen.getByText('未登录')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    expect(screen.getByText('登录 Chronos 账号')).toBeTruthy()
  })

  it('hydrates login state from GET /api/auth/status on mount', async () => {
    mockFetch({ logged_in: true })
    renderWithProviders(<CloudAuthControl collapsed={false} />, {
      preloadedState: { cloudAuth: { isLoggedIn: false, lastErrorCode: null } },
    })

    await waitFor(() => expect(screen.getByText('已登录')).toBeTruthy())
  })

  it('offers re-login and logout when logged in; logout POSTs /api/auth/logout', async () => {
    const calls = mockFetch({ logged_in: true })
    renderWithProviders(<CloudAuthControl collapsed={false} />, {
      preloadedState: { cloudAuth: { isLoggedIn: true, lastErrorCode: null } },
    })

    await userEvent.click(screen.getByRole('button', { name: '账号' }))
    expect(screen.getByText('重新登录')).toBeTruthy()
    await userEvent.click(screen.getByText('登出'))

    await waitFor(() =>
      expect(calls.some((c) => c.url === '/api/auth/logout' && c.method === 'POST')).toBe(true),
    )
  })

  it('renders an icon control with an accessible label when collapsed', () => {
    mockFetch({ logged_in: false })
    renderWithProviders(<CloudAuthControl collapsed />, {
      preloadedState: { cloudAuth: { isLoggedIn: false, lastErrorCode: null } },
    })

    expect(screen.getByRole('button', { name: 'Chronos 账号 · 未登录' })).toBeTruthy()
  })
})
