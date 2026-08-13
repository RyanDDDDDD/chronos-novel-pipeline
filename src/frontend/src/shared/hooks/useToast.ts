import { useCallback, useSyncExternalStore } from 'react'
import { toast } from 'sonner'

export type ToastKind = 'confirm' | 'prompt'

export interface ToastItem {
  id: number
  kind: ToastKind
  message: string
  confirmLabel?: string
  cancelLabel?: string
  onConfirm?: () => void
  onCancel?: () => void
  /** kind === 'prompt' */
  defaultValue?: string
  placeholder?: string
  onPromptSubmit?: (value: string) => void
}

let toasts: ToastItem[] = []
const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach((l) => l())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function getSnapshot(): ToastItem[] {
  return toasts
}

function dismiss(id: number): void {
  toasts = toasts.filter((t) => t.id !== id)
  emit()
}

function pushConfirm(message: string, confirmLabel = '确定', cancelLabel = '取消'): Promise<boolean> {
  return new Promise((resolve) => {
    toasts.filter((t) => t.kind === 'confirm' || t.kind === 'prompt').forEach((t) => t.onCancel?.())

    const id = Date.now() + Math.random()
    const settle = (v: boolean) => { dismiss(id); resolve(v) }
    toasts = [...toasts, {
      id, kind: 'confirm', message, confirmLabel, cancelLabel,
      onConfirm: () => settle(true), onCancel: () => settle(false),
    }]
    emit()
  })
}

function pushPrompt(
  message: string,
  options?: {
    defaultValue?: string
    placeholder?: string
    confirmLabel?: string
    cancelLabel?: string
  },
): Promise<string | null> {
  return new Promise((resolve) => {
    toasts.filter((t) => t.kind === 'confirm' || t.kind === 'prompt').forEach((t) => t.onCancel?.())

    const id = Date.now() + Math.random()
    const settle = (v: string | null) => { dismiss(id); resolve(v) }
    toasts = [...toasts, {
      id,
      kind: 'prompt',
      message,
      defaultValue: options?.defaultValue ?? '',
      placeholder: options?.placeholder,
      confirmLabel: options?.confirmLabel ?? '确定',
      cancelLabel: options?.cancelLabel ?? '取消',
      onPromptSubmit: (value) => settle(value),
      onCancel: () => settle(null),
    }]
    emit()
  })
}

/** confirm/prompt keep the module-level singleton queue ("only one at a time" is project-specific
 * semantics Sonner/Dialog won't enforce); success/error delegate to sonner's toast() API. */
export function useToast(): {
  toasts: ToastItem[]
  dismiss: (id: number) => void
  success: (message: string) => string | number
  error: (message: string) => string | number
  confirm: (message: string, options?: { confirmLabel?: string; cancelLabel?: string }) => Promise<boolean>
  prompt: (
    message: string,
    options?: { defaultValue?: string; placeholder?: string; confirmLabel?: string; cancelLabel?: string },
  ) => Promise<string | null>
} {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot)
  const boundDismiss = useCallback((id: number) => dismiss(id), [])
  const success = useCallback((message: string) => toast.success(message, { duration: 5000 }), [])
  const error = useCallback((message: string) => toast.error(message, { duration: 7000 }), [])
  const confirm = useCallback(
    (message: string, options?: { confirmLabel?: string; cancelLabel?: string }) =>
      pushConfirm(message, options?.confirmLabel, options?.cancelLabel),
    [],
  )
  const prompt = useCallback(
    (message: string, options?: {
      defaultValue?: string
      placeholder?: string
      confirmLabel?: string
      cancelLabel?: string
    }) => pushPrompt(message, options),
    [],
  )
  return { toasts: snapshot, dismiss: boundDismiss, success, error, confirm, prompt }
}
