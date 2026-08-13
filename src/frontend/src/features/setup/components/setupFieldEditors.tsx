import { useEffect, useState } from 'react'
import AutoGrowTextarea from '@/shared/components/AutoGrowTextarea'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Textarea } from '@/shared/components/ui/textarea'

export type FieldSaveResult = { ok: true } | { ok: false; error: string }

export function useFieldSaveState() {
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [error, setError] = useState('')
  return { state, setState, error, setError }
}

export function SaveStatusDot({ state, error }: { state: 'idle' | 'saving' | 'saved' | 'error'; error: string }) {
  if (state === 'idle') return null
  if (state === 'saving') return <span className="text-xs text-[var(--c-text-muted)]">保存中…</span>
  if (state === 'error') return <span className="text-xs text-red-600">{error || '保存失败'}</span>
  return <span className="text-xs text-emerald-600">已保存</span>
}

export function EditableInputField({
  label,
  value,
  onSave,
  className = '',
}: {
  label: string
  value: string
  onSave: (next: string) => Promise<FieldSaveResult>
  className?: string
}) {
  const [draft, setDraft] = useState(value)
  const { state, setState, error, setError } = useFieldSaveState()
  useEffect(() => setDraft(value), [value])

  const handleBlur = async () => {
    if (draft === value) return
    setState('saving')
    const res = await onSave(draft)
    if (res.ok) {
      setState('saved')
      setError('')
    } else {
      setState('error')
      setError(res.error)
    }
  }

  return (
    <div className={className}>
      <div className="flex items-center gap-2 mb-1.5">
        {label ? <Label className="text-xs font-medium text-[var(--c-text-muted)]">{label}</Label> : null}
        <SaveStatusDot state={state} error={error} />
      </div>
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={handleBlur}
      />
    </div>
  )
}

export function EditableTextField({
  label,
  value,
  onSave,
  className = '',
  rows = 3,
}: {
  label: string
  value: string
  onSave: (next: string) => Promise<FieldSaveResult>
  className?: string
  rows?: number
}) {
  const [draft, setDraft] = useState(value)
  const { state, setState, error, setError } = useFieldSaveState()
  useEffect(() => setDraft(value), [value])

  const handleBlur = async () => {
    if (draft === value) return
    setState('saving')
    const res = await onSave(draft)
    if (res.ok) {
      setState('saved')
      setError('')
    } else {
      setState('error')
      setError(res.error)
    }
  }

  return (
    <div className={className}>
      <div className="flex items-center gap-2 mb-1.5">
        {label ? <Label className="text-xs font-medium text-[var(--c-text-muted)]">{label}</Label> : null}
        <SaveStatusDot state={state} error={error} />
      </div>
      <Textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={handleBlur}
        rows={rows}
        className="min-h-0 resize-none leading-relaxed"
      />
    </div>
  )
}

export function TagListEditor({
  label,
  tags,
  onSave,
}: {
  label: string
  tags: string[]
  onSave: (next: string[]) => Promise<FieldSaveResult>
}) {
  const [local, setLocal] = useState(tags)
  useEffect(() => setLocal(tags), [tags])
  const [draft, setDraft] = useState('')
  const { state, setState, error, setError } = useFieldSaveState()

  const persist = async (next: string[]) => {
    setLocal(next)
    setState('saving')
    const res = await onSave(next)
    if (res.ok) {
      setState('saved')
      setError('')
    } else {
      setState('error')
      setError(res.error)
    }
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-1.5">
        <div className="text-xs font-medium text-[var(--c-text-muted)]">{label}</div>
        <SaveStatusDot state={state} error={error} />
      </div>
      <div className="flex flex-wrap gap-1.5 items-center">
        {local.map((t, i) => (
          <span
            key={i}
            className="px-2 py-0.5 rounded-full bg-[var(--c-surface-muted)] text-xs text-[var(--c-text-secondary)] flex items-center gap-1"
          >
            {t}
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              onClick={() => void persist(local.filter((_, j) => j !== i))}
              aria-label={`删除${t}`}
              className="h-auto w-auto p-0"
            >
              ✕
            </Button>
          </span>
        ))}
        <Input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && draft.trim()) {
              void persist([...local, draft.trim()])
              setDraft('')
            }
          }}
          placeholder="回车新增"
          className="rounded-full w-20 h-auto text-xs px-2 py-1"
        />
      </div>
    </div>
  )
}

export function CausalAnchorsEditor({
  anchors,
  onSave,
}: {
  anchors: Record<string, string>
  onSave: (next: Record<string, string>) => Promise<FieldSaveResult>
}) {
  const [local, setLocal] = useState(anchors)
  useEffect(() => setLocal(anchors), [anchors])
  const [newKey, setNewKey] = useState('')
  const { state, setState, error, setError } = useFieldSaveState()

  const persist = async (next: Record<string, string>) => {
    setLocal(next)
    setState('saving')
    const res = await onSave(next)
    if (res.ok) {
      setState('saved')
      setError('')
    } else {
      setState('error')
      setError(res.error)
    }
  }

  return (
    <section>
      <div className="flex items-center gap-2 mb-1.5">
        <div className="text-xs font-medium text-[var(--c-text-muted)]">因果锚点</div>
        <SaveStatusDot state={state} error={error} />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {Object.entries(local).map(([k, v]) => (
          <div key={k} className="rounded-lg border border-amber-100 bg-amber-50/50 px-2.5 py-2 space-y-1">
            <div className="flex items-center gap-1">
              <span className="text-xs font-medium text-amber-800 flex-1">{k}</span>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  const { [k]: _drop, ...rest } = local
                  void persist(rest)
                }}
                aria-label={`删除${k}`}
                className="text-xs text-red-500 hover:text-red-700 h-auto p-0"
              >
                ✕
              </Button>
            </div>
            <AutoGrowTextarea
              value={v}
              onChange={(e) => setLocal((prev) => ({ ...prev, [k]: e.target.value }))}
              onBlur={() => void persist(local)}
              rows={1}
              minPx={28}
              maxPx={240}
              className="w-full text-sm text-[var(--c-text-secondary)] bg-transparent focus:outline-none focus:ring-2 focus:ring-[var(--c-focus-ring)] rounded resize-none"
            />
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 mt-2">
        <Input
          type="text"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          placeholder="新锚点名"
          className="rounded-full w-28 h-auto text-xs px-2 py-1"
        />
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            if (!newKey.trim() || newKey in local) return
            void persist({ ...local, [newKey.trim()]: '' })
            setNewKey('')
          }}
          className="text-xs px-2 py-1 h-auto rounded-lg border-[var(--c-tag-violet-border)] text-[var(--c-accent)] hover:bg-[var(--c-accent-subtle)]"
        >
          + 新增
        </Button>
      </div>
    </section>
  )
}
