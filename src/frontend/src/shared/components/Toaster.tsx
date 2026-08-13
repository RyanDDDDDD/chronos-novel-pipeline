import { useState } from 'react'
import type { ToastItem } from '@/shared/hooks/useToast'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'

interface Props {
  toasts: ToastItem[]
  onDismiss: (id: number) => void
}

function PromptDialogFields({ toast }: { toast: ToastItem }) {
  const [value, setValue] = useState(toast.defaultValue ?? '')

  const submit = () => {
    const trimmed = value.trim()
    if (!trimmed) return
    toast.onPromptSubmit?.(trimmed)
  }

  return (
    <>
      <Input
        autoFocus
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={toast.placeholder}
        aria-label={toast.message}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            submit()
          }
        }}
      />
      <DialogFooter>
        <Button type="button" variant="outline" onClick={toast.onCancel}>
          {toast.cancelLabel}
        </Button>
        <Button type="button" variant="default" onClick={submit} disabled={!value.trim()}>
          {toast.confirmLabel}
        </Button>
      </DialogFooter>
    </>
  )
}

export default function Toaster({ toasts }: Props) {
  const active = toasts[0] ?? null

  const handleOpenChange = (open: boolean) => {
    if (open || !active) return
    active.onCancel?.()
  }

  if (!active) return null

  return (
    <Dialog open onOpenChange={handleOpenChange}>
      <DialogContent
        className="sm:max-w-sm"
        onKeyDown={(e) => {
          if (active.kind !== 'confirm' || e.key !== 'Enter') return
          e.preventDefault()
          active.onConfirm?.()
        }}
      >
        <DialogHeader>
          <DialogTitle className="sr-only">{active.kind === 'confirm' ? '确认' : '输入'}</DialogTitle>
          <DialogDescription>{active.message}</DialogDescription>
        </DialogHeader>
        {active.kind === 'confirm' && (
          <DialogFooter>
            <Button type="button" variant="outline" onClick={active.onCancel}>
              {active.cancelLabel}
            </Button>
            <Button type="button" variant="destructive" onClick={active.onConfirm}>
              {active.confirmLabel}
            </Button>
          </DialogFooter>
        )}
        {active.kind === 'prompt' && <PromptDialogFields toast={active} />}
      </DialogContent>
    </Dialog>
  )
}
