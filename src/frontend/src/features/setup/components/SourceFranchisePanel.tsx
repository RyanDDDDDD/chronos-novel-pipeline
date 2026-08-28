import { useState } from 'react'
import { useSourceFranchise, useSetSourceFranchise } from '@/features/setup/queries/sourceFranchise'
import { useToast } from '@/shared/hooks/useToast'
import { Button } from '@/shared/components/ui/button'

const fieldClass =
  'w-full px-2 py-1.5 text-xs rounded-md border border-[var(--c-border)] bg-[var(--c-surface)] ' +
  'text-[var(--c-text)] focus:outline-none focus:ring-1 focus:ring-[var(--c-focus-ring)] ' +
  'focus:border-[var(--c-accent)] disabled:opacity-50'

/** Per-novel「原作出处」setting: the existing work this novel is fan fiction of. Filling it
 *  in lets character portraits anchor to the original design via danbooru identity tags. */
export default function SourceFranchisePanel({
  novelId, onClose,
}: { novelId: string; onClose?: () => void }) {
  const { data: stored } = useSourceFranchise(novelId)
  const save = useSetSourceFranchise(novelId)
  const { success: toastSuccess, error: toastError } = useToast()
  // `draft` is null until the user types -- until then the input mirrors the server value.
  const [draft, setDraft] = useState<string | null>(null)
  const value = draft ?? stored ?? ''

  const handleSave = async () => {
    if (!novelId || save.isPending) return
    const r = await save.mutateAsync(value)
    if (r.ok) {
      toastSuccess('原作出处已保存，立绘提示词将在后台重新提取')
      onClose?.()
    } else {
      toastError(r.error ?? '保存失败')
    }
  }

  return (
    <div className="space-y-2">
      <label className="block text-[11px] text-[var(--c-text-muted)] mb-1">原作出处（同人）</label>
      <input
        type="text"
        value={value}
        onChange={(e) => setDraft(e.target.value)}
        disabled={save.isPending}
        placeholder="如「碧蓝档案」/「Blue Archive」；原创小说留空"
        className={fieldClass}
      />
      <p className="text-[10px] leading-snug text-[var(--c-text-faint)]">
        填了之后，各角色立绘会尝试按 danbooru 角色标签锚定原作形象；也可逐角色在档案里加「形象锚定」段落覆盖。
      </p>
      <div className="flex justify-end gap-2">
        {onClose && (
          <Button
            type="button"
            variant="ghost"
            onClick={onClose}
            disabled={save.isPending}
            className="px-2.5 py-1 h-auto text-xs text-[var(--c-text-muted)] hover:bg-[var(--c-surface-hover)]"
          >
            取消
          </Button>
        )}
        <Button
          type="button"
          variant="default"
          onClick={() => void handleSave()}
          disabled={save.isPending}
          className="px-2.5 py-1 h-auto text-xs"
        >
          {save.isPending ? '保存中…' : '保存'}
        </Button>
      </div>
    </div>
  )
}
