import { useEffect, useState } from 'react'
import { Eye } from 'lucide-react'
import { useProseStyles, useProseStyle, useSetProseStyle } from '@/features/setup/queries/proseStyle'
import AutoGrowTextarea from '@/shared/components/AutoGrowTextarea'
import ChatMarkdown from '@/shared/components/ChatMarkdown'
import ProseStylePreviewDialog from '@/features/setup/components/ProseStylePreviewDialog'
import { useToast } from '@/shared/hooks/useToast'
import { Button } from '@/shared/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'

const labelClass = 'block text-[11px] text-slate-500 mb-1'
const fieldClass =
  'w-full px-2 py-1.5 text-xs rounded-md border border-slate-200 bg-white ' +
  'focus:outline-none focus:ring-1 focus:ring-[var(--c-focus-ring)] focus:border-[var(--c-accent)] disabled:opacity-50'

/**
 *Per-novel writing style setting card: language sense color preset + custom addition.
 *Popover mode (default) renders a floating card; embedded mode strips chrome for side panels.
 */
export default function ProseStylePanel({
  novelId, onClose, embedded = false,
}: { novelId: string; onClose?: () => void; embedded?: boolean }) {
  const { data: presets = [] } = useProseStyles()
  const { data: cfg } = useProseStyle(novelId)
  const save = useSetProseStyle(novelId)
  const { success: toastSuccess, error: toastError } = useToast()
  const [preset, setPreset] = useState('')
  const [addendum, setAddendum] = useState('')
  const [showPreview, setShowPreview] = useState(false)
  const [editingAddendum, setEditingAddendum] = useState(false)

  useEffect(() => {
    if (cfg) {
      setPreset(cfg.preset)
      setAddendum(cfg.custom_addendum)
      setEditingAddendum(!cfg.custom_addendum)
    }
  }, [cfg])

  const handleSave = async () => {
    if (!novelId || save.isPending) return
    const r = await save.mutateAsync({ preset, custom_addendum: addendum })
    if (r.ok) {
      setEditingAddendum(!addendum)
      toastSuccess('文风已保存')
      onClose?.()
    } else {
      toastError(r.error ?? '保存失败')
    }
  }

  return (
    <div className={embedded ? 'space-y-2' : 'w-64 rounded-lg border border-slate-200 bg-white p-3 shadow-float'}>
      {!embedded && (
        <div className="text-xs font-semibold text-slate-700 mb-2">文风（当前小说）</div>
      )}
      <label className={labelClass}>语感调色</label>
      <div className="flex gap-1.5 mb-2">
        <Select value={preset} onValueChange={setPreset} disabled={save.isPending}>
          <SelectTrigger className={fieldClass}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {presets.map(s => <SelectItem key={s.id} value={s.id}>{s.title}</SelectItem>)}
          </SelectContent>
        </Select>
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => setShowPreview(true)}
          disabled={!preset}
          title="预览文风内容"
          className="shrink-0"
        >
          <Eye size={14} />
        </Button>
      </div>
      <label className={labelClass}>自定义追加</label>
      {editingAddendum ? (
        <AutoGrowTextarea
          value={addendum}
          onChange={e => setAddendum(e.target.value)}
          onBlur={() => { if (addendum) setEditingAddendum(false) }}
          disabled={save.isPending}
          autoFocus
          rows={3}
          minPx={62}
          maxPx={420}
          placeholder="可选：本书额外文风要求（支持 Markdown）"
          className={`${fieldClass} mb-2 resize-none`}
        />
      ) : (
        <div
          role="button"
          tabIndex={0}
          title="点击编辑"
          onClick={() => setEditingAddendum(true)}
          onKeyDown={e => { if (e.key === 'Enter') setEditingAddendum(true) }}
          className={`${fieldClass} mb-2 text-xs leading-snug cursor-text hover:border-[var(--c-accent)]`}
        >
          <ChatMarkdown content={addendum} />
        </div>
      )}
      <div className="flex justify-end gap-2">
        {onClose && (
          <Button type="button" variant="ghost" onClick={onClose} disabled={save.isPending}
            className="px-2.5 py-1 h-auto text-xs text-slate-500 hover:bg-slate-50">
            取消
          </Button>
        )}
        <Button type="button" variant="default" onClick={() => void handleSave()} disabled={save.isPending}
          className="px-2.5 py-1 h-auto text-xs">
          {save.isPending ? '保存中…' : '保存'}
        </Button>
      </div>
      {showPreview && (
        <ProseStylePreviewDialog
          presetId={preset}
          title={presets.find(s => s.id === preset)?.title ?? preset}
          onClose={() => setShowPreview(false)}
        />
      )}
    </div>
  )
}
