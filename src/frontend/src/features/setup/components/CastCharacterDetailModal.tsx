import { useEffect, useMemo, useState } from 'react'
import { useSelector } from 'react-redux'
import { Eye, Pencil, X, RefreshCw, Loader2 } from 'lucide-react'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Button } from '@/shared/components/ui/button'
import type { CastCharacter, CastCharacterInput, CustomFieldSpec, RelationshipGraph } from '@/shared/types'
import { useToast } from '@/shared/hooks/useToast'
import { castDisplayName } from '@/features/setup/components/castCharacterDisplay'
import { CastCharacterMarkdownContent } from '@/features/setup/components/CastCharacterMarkdownView'
import { buildCastCharacterMarkdown } from '@/features/setup/utils/castCharacterMarkdown'
import { buildCastCharacterPatchPayload } from '@/features/setup/utils/castCharacterPatchPayload'
import { parseCastCharacterMarkdown } from '@/features/setup/utils/parseCastCharacterMarkdown'
import { castPortraitUrl } from '@/features/setup/utils/castPortraitUrl'
import { regenerateCastPortrait } from '@/features/setup/utils/regenerateCastPortrait'
import { selectPortraitGenerating } from '@/shared/store/portraitGenerationSlice'
import { useActiveNovelId } from '@/shared/queries/novels'

type ModalMode = 'preview' | 'edit'

function buildEditableMarkdown(
  character: CastCharacter,
  customFieldSpecs: CustomFieldSpec[],
  relationshipGraph?: RelationshipGraph,
): string {
  const portraitUrl = castPortraitUrl(character.name, character.portrait_path)
  return buildCastCharacterMarkdown(character, {
    customFieldSpecs,
    relationshipGraph,
    portraitUrl,
  })
}

export default function CastCharacterDetailModal({
  character,
  open,
  onOpenChange,
  onSave,
  relationshipGraph,
  customFieldSpecs,
}: {
  character: CastCharacter | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSave: (name: string, fields: CastCharacterInput) => Promise<{ ok: true; character: CastCharacter } | { ok: false; error: string }>
  relationshipGraph?: RelationshipGraph
  customFieldSpecs: CustomFieldSpec[]
}) {
  const { error: toastError, success: toastSuccess } = useToast()
  const [mode, setMode] = useState<ModalMode>('preview')
  const [draft, setDraft] = useState('')
  const [baseline, setBaseline] = useState('')
  const [saving, setSaving] = useState(false)

  const snapshotMarkdown = useMemo(
    () => (character ? buildEditableMarkdown(character, customFieldSpecs, relationshipGraph) : ''),
    [character, customFieldSpecs, relationshipGraph],
  )

  useEffect(() => {
    if (open && character) {
      setDraft(snapshotMarkdown)
      setBaseline(snapshotMarkdown)
      setMode('preview')
    }
  }, [open, character, snapshotMarkdown])

  const novelId = useActiveNovelId()
  const generationStatus = useSelector(selectPortraitGenerating(novelId, character?.name ?? ''))

  if (!character) return null

  const displayName = castDisplayName(character)
  const editing = mode === 'edit'
  const generating = generationStatus === 'generating'

  const handleRegeneratePortrait = async () => {
    const res = await regenerateCastPortrait(character.name)
    if (!res.ok) toastError(`立绘生成请求失败：${res.error}`)
  }

  const handleOpenChange = (next: boolean) => {
    if (next) {
      onOpenChange(true)
      return
    }
    if (saving) return

    const trimmedDraft = draft.trim()
    const trimmedBaseline = baseline.trim()
    if (trimmedDraft === trimmedBaseline) {
      onOpenChange(false)
      return
    }

    void (async () => {
      setSaving(true)
      try {
        const parsed = parseCastCharacterMarkdown(draft, { customFieldSpecs, baseline: character })
        const payload = buildCastCharacterPatchPayload(character, parsed, customFieldSpecs)
        const res = await onSave(character.name, payload)
        if (!res.ok) {
          toastError(`保存失败：${res.error}`)
          return
        }
        toastSuccess('角色档案已保存')
        onOpenChange(false)
      } catch (err) {
        toastError(`解析失败：${err instanceof Error ? err.message : String(err)}`)
      } finally {
        setSaving(false)
      }
    })()
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="max-w-3xl max-h-[90vh] flex flex-col overflow-hidden p-0 gap-0 sm:max-w-3xl"
      >
        <DialogHeader className="px-6 py-3 border-b border-[var(--c-border-subtle)] shrink-0">
          <div className="flex items-start gap-4">
            <div className="min-w-0 flex-1">
              <DialogTitle className="text-sm font-semibold text-[var(--c-text)]">{displayName}</DialogTitle>
              <p className="text-xs text-[var(--c-text-faint)] mt-0.5">
                {editing ? '编辑 Markdown 源码，关闭弹窗时自动保存' : '档案预览'}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={generating || saving}
                onClick={() => void handleRegeneratePortrait()}
                aria-label="重新生成立绘"
              >
                {generating ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                重新生成立绘
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-pressed={editing}
                disabled={saving}
                onClick={() => setMode(editing ? 'preview' : 'edit')}
              >
                {editing ? (
                  <>
                    <Eye />
                    预览
                  </>
                ) : (
                  <>
                    <Pencil />
                    编辑
                  </>
                )}
              </Button>
              <DialogClose asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  disabled={saving}
                  aria-label="关闭"
                  className="text-[var(--c-text-muted)] hover:bg-[var(--c-surface-hover)] hover:text-[var(--c-text)]"
                >
                  <X />
                </Button>
              </DialogClose>
            </div>
          </div>
        </DialogHeader>
        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4 text-sm text-[var(--c-text-secondary)]">
          {editing ? (
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={saving}
              aria-label={`编辑${displayName}档案`}
              spellCheck={false}
              className="h-full min-h-[50vh] w-full resize-none rounded-md border border-[var(--c-border)] bg-[var(--c-surface)] px-3 py-2 font-mono text-sm leading-relaxed text-[var(--c-text-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--c-focus-ring)] disabled:opacity-60"
            />
          ) : (
            <>
              <CastCharacterMarkdownContent content={draft} />
              {!character.portrait_visual_tags && (
                <div className="mt-4 rounded-md border border-dashed border-[var(--c-border)] px-3 py-2">
                  <p className="text-xs font-medium text-[var(--c-text-faint)]">生图提示词</p>
                  <p className="mt-1 text-xs font-mono text-[var(--c-text-muted)]">
                    尚未生成，首次生图时自动提取；也可以点「编辑」手动添加「生图提示词」段落。
                  </p>
                </div>
              )}
              {!character.portrait_identity_tags && (
                <div className="mt-2 rounded-md border border-dashed border-[var(--c-border)] px-3 py-2">
                  <p className="text-xs font-medium text-[var(--c-text-faint)]">形象锚定</p>
                  <p className="mt-1 text-xs text-[var(--c-text-muted)]">
                    这个角色若出自某个已有作品，可在「编辑」里加「形象锚定」段落，填该角色的 booru 标签
                    （如 <span className="font-mono">shiroko (blue archive), blue archive</span>），让立绘贴合原作形象。
                  </p>
                </div>
              )}
            </>
          )}
        </div>
        <div className="shrink-0 px-6 py-2 border-t border-[var(--c-border-subtle)] text-xs text-[var(--c-text-faint)]">
          {saving
            ? '保存中…'
            : editing
              ? '「身份」「关系」「成长轴」段落在关闭时不会写回'
              : '点「编辑」修改档案，关闭弹窗时自动保存'}
        </div>
      </DialogContent>
    </Dialog>
  )
}
