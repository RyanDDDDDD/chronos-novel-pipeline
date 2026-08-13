// @vitest-environment jsdom
// renderHook mounts a real component tree -- this repo's environmentMatchGlobs only grants
// jsdom to .test.tsx files by default, so a plain .test.ts needs this per-file override.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { toast } from 'sonner'
import { useToast } from '@/shared/hooks/useToast'

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(() => 'sonner-success-id'),
    error: vi.fn(() => 'sonner-error-id'),
  },
}))

describe('useToast', () => {
  beforeEach(() => {
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
    vi.useFakeTimers()
  })
  afterEach(() => {
    const { result } = renderHook(() => useToast())
    act(() => { result.current.toasts.forEach((t) => result.current.dismiss(t.id)) })
    vi.useRealTimers()
  })

  it('success/error delegate to sonner and do not enter the confirm/prompt queue', () => {
    const a = renderHook(() => useToast())
    const b = renderHook(() => useToast())
    act(() => { a.result.current.success('已保存') })
    act(() => { a.result.current.error('失败') })
    expect(toast.success).toHaveBeenCalledWith('已保存', { duration: 5000 })
    expect(toast.error).toHaveBeenCalledWith('失败', { duration: 7000 })
    expect(a.result.current.toasts).toHaveLength(0)
    expect(b.result.current.toasts).toHaveLength(0)
  })

  it('two independent hook instances share the same confirm/prompt queue', () => {
    const a = renderHook(() => useToast())
    const b = renderHook(() => useToast())
    act(() => { a.result.current.confirm('删除？') })
    expect(a.result.current.toasts).toHaveLength(1)
    expect(b.result.current.toasts).toHaveLength(1)
    expect(b.result.current.toasts[0].message).toBe('删除？')
  })

  it('confirm() resolves true when the confirm button fires, and does not auto-dismiss', async () => {
    const { result } = renderHook(() => useToast())
    let resolved: boolean | undefined
    act(() => {
      result.current.confirm('删除当前小说？').then((v) => { resolved = v })
    })
    expect(result.current.toasts).toHaveLength(1)
    expect(result.current.toasts[0].kind).toBe('confirm')
    act(() => { vi.advanceTimersByTime(60_000) })
    expect(result.current.toasts).toHaveLength(1)
    act(() => { result.current.toasts[0].onConfirm?.() })
    await Promise.resolve()
    expect(resolved).toBe(true)
    expect(result.current.toasts).toHaveLength(0)
  })

  it('confirm() resolves false when the cancel button fires', async () => {
    const { result } = renderHook(() => useToast())
    let resolved: boolean | undefined
    act(() => {
      result.current.confirm('删除当前小说？').then((v) => { resolved = v })
    })
    act(() => { result.current.toasts[0].onCancel?.() })
    await Promise.resolve()
    expect(resolved).toBe(false)
    expect(result.current.toasts).toHaveLength(0)
  })

  it('a second confirm() call (e.g. a double click) settles the stale dialog as cancelled instead of stacking', async () => {
    const { result } = renderHook(() => useToast())
    let firstResolved: boolean | undefined
    let secondResolved: boolean | undefined
    act(() => {
      result.current.confirm('删除当前小说？').then((v) => { firstResolved = v })
    })
    act(() => {
      result.current.confirm('删除当前小说？').then((v) => { secondResolved = v })
    })
    await Promise.resolve()
    expect(firstResolved).toBe(false)
    expect(secondResolved).toBeUndefined()
    expect(result.current.toasts).toHaveLength(1)
    act(() => { result.current.toasts[0].onConfirm?.() })
    await Promise.resolve()
    expect(secondResolved).toBe(true)
    expect(result.current.toasts).toHaveLength(0)
  })
})
