import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react'
import CloudLoginDialog from '@/features/services/components/CloudLoginDialog'

type FetchCall = { url: string; body: Record<string, unknown> }

function mockFetch(responses: Record<string, { ok: boolean; body: Record<string, unknown> }>) {
  const calls: FetchCall[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(init.body as string) : {}
    calls.push({ url, body })
    const resp = responses[url] ?? { ok: true, body: {} }
    return { ok: resp.ok, json: async () => resp.body }
  }))
  return calls
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('CloudLoginDialog', () => {
  it('renders nothing when closed', () => {
    mockFetch({})
    render(<CloudLoginDialog open={false} onClose={vi.fn()} />)
    expect(screen.queryByText('登录 Chronos 账号')).toBeNull()
  })

  it('shows the login form by default', () => {
    mockFetch({})
    render(<CloudLoginDialog open={true} onClose={vi.fn()} />)
    expect(screen.getByText('登录 Chronos 账号')).toBeTruthy()
    expect(screen.getByPlaceholderText('邮箱')).toBeTruthy()
  })

  it('switches to the register form via the register link', () => {
    mockFetch({})
    render(<CloudLoginDialog open={true} onClose={vi.fn()} />)
    fireEvent.click(screen.getByText('没有账号？注册'))
    expect(screen.getByText('注册 Chronos 账号')).toBeTruthy()
    expect(screen.getByPlaceholderText('确认密码')).toBeTruthy()
  })

  it('rejects mismatched passwords locally without calling the API', async () => {
    const calls = mockFetch({})
    render(<CloudLoginDialog open={true} onClose={vi.fn()} />)
    fireEvent.click(screen.getByText('没有账号？注册'))

    fireEvent.change(screen.getByPlaceholderText('邮箱'), { target: { value: 'a@b.com' } })
    fireEvent.change(screen.getByPlaceholderText('密码（至少 8 位，含大小写字母和数字）'), { target: { value: 'Password123!' } })
    fireEvent.change(screen.getByPlaceholderText('确认密码'), { target: { value: 'Different123!' } })
    fireEvent.click(screen.getByText('注册'))

    await waitFor(() => expect(screen.getByText('两次输入的密码不一致')).toBeTruthy())
    expect(calls).toHaveLength(0)
  })

  it('moves to the confirmation step after successful registration', async () => {
    mockFetch({
      '/api/auth/register': { ok: true, body: { user_sub: 'sub-1', email_verification_required: true } },
    })
    render(<CloudLoginDialog open={true} onClose={vi.fn()} />)
    fireEvent.click(screen.getByText('没有账号？注册'))

    fireEvent.change(screen.getByPlaceholderText('邮箱'), { target: { value: 'a@b.com' } })
    fireEvent.change(screen.getByPlaceholderText('密码（至少 8 位，含大小写字母和数字）'), { target: { value: 'Password123!' } })
    fireEvent.change(screen.getByPlaceholderText('确认密码'), { target: { value: 'Password123!' } })
    fireEvent.click(screen.getByText('注册'))

    await waitFor(() => expect(screen.getByText('验证邮箱')).toBeTruthy())
    expect(screen.getByText('验证码已发送到 a@b.com，请查收并输入')).toBeTruthy()
  })

  it('shows a mapped Chinese error when registration fails', async () => {
    mockFetch({
      '/api/auth/register': { ok: false, body: { error_code: 'EMAIL_ALREADY_EXISTS' } },
    })
    render(<CloudLoginDialog open={true} onClose={vi.fn()} />)
    fireEvent.click(screen.getByText('没有账号？注册'))

    fireEvent.change(screen.getByPlaceholderText('邮箱'), { target: { value: 'a@b.com' } })
    fireEvent.change(screen.getByPlaceholderText('密码（至少 8 位，含大小写字母和数字）'), { target: { value: 'Password123!' } })
    fireEvent.change(screen.getByPlaceholderText('确认密码'), { target: { value: 'Password123!' } })
    fireEvent.click(screen.getByText('注册'))

    await waitFor(() => expect(screen.getByText('该邮箱已注册，请直接登录')).toBeTruthy())
    expect(screen.getByText('注册 Chronos 账号')).toBeTruthy() // stayed on register step
  })

  it('confirms and auto-logs in, then closes the dialog', async () => {
    const onClose = vi.fn()
    mockFetch({
      '/api/auth/register': { ok: true, body: { user_sub: 'sub-1', email_verification_required: true } },
      '/api/auth/confirm': { ok: true, body: { ok: true } },
      '/api/auth/login': { ok: true, body: { ok: true } },
    })
    render(<CloudLoginDialog open={true} onClose={onClose} />)
    fireEvent.click(screen.getByText('没有账号？注册'))
    fireEvent.change(screen.getByPlaceholderText('邮箱'), { target: { value: 'a@b.com' } })
    fireEvent.change(screen.getByPlaceholderText('密码（至少 8 位，含大小写字母和数字）'), { target: { value: 'Password123!' } })
    fireEvent.change(screen.getByPlaceholderText('确认密码'), { target: { value: 'Password123!' } })
    fireEvent.click(screen.getByText('注册'))
    await waitFor(() => expect(screen.getByText('验证邮箱')).toBeTruthy())

    fireEvent.change(screen.getByPlaceholderText('验证码'), { target: { value: '123456' } })
    fireEvent.click(screen.getByText('确认'))

    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('shows a mapped error and stays on the confirm step when the code is wrong', async () => {
    mockFetch({
      '/api/auth/register': { ok: true, body: { user_sub: 'sub-1', email_verification_required: true } },
      '/api/auth/confirm': { ok: false, body: { error_code: 'CODE_MISMATCH' } },
    })
    render(<CloudLoginDialog open={true} onClose={vi.fn()} />)
    fireEvent.click(screen.getByText('没有账号？注册'))
    fireEvent.change(screen.getByPlaceholderText('邮箱'), { target: { value: 'a@b.com' } })
    fireEvent.change(screen.getByPlaceholderText('密码（至少 8 位，含大小写字母和数字）'), { target: { value: 'Password123!' } })
    fireEvent.change(screen.getByPlaceholderText('确认密码'), { target: { value: 'Password123!' } })
    fireEvent.click(screen.getByText('注册'))
    await waitFor(() => expect(screen.getByText('验证邮箱')).toBeTruthy())

    fireEvent.change(screen.getByPlaceholderText('验证码'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByText('确认'))

    await waitFor(() => expect(screen.getByText('验证码不正确')).toBeTruthy())
    expect(screen.getByText('验证邮箱')).toBeTruthy() // stayed on confirm step
  })

  it('returns to the login form from the register step', () => {
    mockFetch({})
    render(<CloudLoginDialog open={true} onClose={vi.fn()} />)
    fireEvent.click(screen.getByText('没有账号？注册'))
    fireEvent.click(screen.getByText('返回登录'))
    expect(screen.getByText('登录 Chronos 账号')).toBeTruthy()
  })
})
