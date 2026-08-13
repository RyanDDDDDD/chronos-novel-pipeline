import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Toaster from '@/shared/components/Toaster'
import type { ToastItem } from '@/shared/hooks/useToast'

beforeEach(() => cleanup())

describe('Toaster confirm variant', () => {
  it('renders confirm/cancel buttons in a dialog, and fires the right callback', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    const toasts: ToastItem[] = [{
      id: 1, kind: 'confirm', message: '删除当前小说？',
      confirmLabel: '确定', cancelLabel: '取消', onConfirm, onCancel,
    }]
    render(<Toaster toasts={toasts} onDismiss={vi.fn()} />)
    expect(screen.getByRole('dialog')).toBeTruthy()
    screen.getByText('删除当前小说？')
    await userEvent.click(screen.getByRole('button', { name: '确定' }))
    expect(onConfirm).toHaveBeenCalled()
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('cancel button fires onCancel', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    const toasts: ToastItem[] = [{
      id: 1, kind: 'confirm', message: '删除？',
      confirmLabel: '确定', cancelLabel: '取消', onConfirm, onCancel,
    }]
    render(<Toaster toasts={toasts} onDismiss={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(onCancel).toHaveBeenCalled()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('Enter key fires onConfirm on confirm dialog', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    const toasts: ToastItem[] = [{
      id: 1, kind: 'confirm', message: '删除？',
      confirmLabel: '确定', cancelLabel: '取消', onConfirm, onCancel,
    }]
    render(<Toaster toasts={toasts} onDismiss={vi.fn()} />)
    const dialog = screen.getByRole('dialog')
    fireEvent.keyDown(dialog, { key: 'Enter' })
    expect(onConfirm).toHaveBeenCalled()
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('Escape closes dialog and fires onCancel', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    const toasts: ToastItem[] = [{
      id: 1, kind: 'confirm', message: '删除？',
      confirmLabel: '确定', cancelLabel: '取消', onConfirm, onCancel,
    }]
    render(<Toaster toasts={toasts} onDismiss={vi.fn()} />)
    await userEvent.keyboard('{Escape}')
    expect(onCancel).toHaveBeenCalled()
    expect(onConfirm).not.toHaveBeenCalled()
  })
})

describe('Toaster prompt variant', () => {
  it('submits trimmed input via onPromptSubmit', async () => {
    const onPromptSubmit = vi.fn()
    const onCancel = vi.fn()
    const toasts: ToastItem[] = [{
      id: 1, kind: 'prompt', message: '新小说名称',
      confirmLabel: '创建', cancelLabel: '取消', onPromptSubmit, onCancel,
      placeholder: '请输入小说名称',
    }]
    render(<Toaster toasts={toasts} onDismiss={vi.fn()} />)
    const input = screen.getByPlaceholderText('请输入小说名称')
    await userEvent.clear(input)
    await userEvent.type(input, ' 甲小说 ')
    await userEvent.click(screen.getByRole('button', { name: '创建' }))
    expect(onPromptSubmit).toHaveBeenCalledWith('甲小说')
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('cancel button fires onCancel', async () => {
    const onPromptSubmit = vi.fn()
    const onCancel = vi.fn()
    const toasts: ToastItem[] = [{
      id: 1, kind: 'prompt', message: '新小说名称',
      confirmLabel: '创建', cancelLabel: '取消', onPromptSubmit, onCancel,
    }]
    render(<Toaster toasts={toasts} onDismiss={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(onCancel).toHaveBeenCalled()
    expect(onPromptSubmit).not.toHaveBeenCalled()
  })
})
