import { useState } from 'react'
import { useSelector } from 'react-redux'
import { RefreshCw, Loader2 } from 'lucide-react'
import type { CastCharacter } from '@/shared/types'
import { Button } from '@/shared/components/ui/button'
import { useToast } from '@/shared/hooks/useToast'
import { castPortraitUrl } from '@/features/setup/utils/castPortraitUrl'
import { regenerateCastPortrait } from '@/features/setup/utils/regenerateCastPortrait'
import { castDisplayName, CastCharacterTags } from '@/features/setup/components/castCharacterDisplay'
import { selectPortraitGenerating } from '@/shared/store/portraitGenerationSlice'
import { useActiveNovelId } from '@/shared/queries/novels'

export default function CastCharacterGridCard({
  character,
  onOpen,
  onDelete,
}: {
  character: CastCharacter
  onOpen: () => void
  onDelete: (name: string) => Promise<{ ok: true } | { ok: false; error: string }>
}) {
  const { confirm, error: toastError } = useToast()
  const novelId = useActiveNovelId()
  const generationStatus = useSelector(selectPortraitGenerating(novelId, character.name))
  const [portraitFailed, setPortraitFailed] = useState(false)
  const portraitUrl = castPortraitUrl(character.name, character.portrait_path)
  const showPortrait = Boolean(portraitUrl) && !portraitFailed
  const displayName = castDisplayName(character)
  const generating = generationStatus === 'generating'

  const handleDelete = async () => {
    if (!(await confirm(`删除角色「${displayName}」？此操作不可撤销。`))) return
    await onDelete(character.name)
  }

  const handleRegenerate = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const res = await regenerateCastPortrait(character.name)
    if (!res.ok) toastError(`立绘生成请求失败：${res.error}`)
  }

  const showBackdrop = showPortrait || generating || generationStatus === 'failed'

  return (
    <div className="group relative aspect-[2/3] rounded-lg border border-[var(--c-border)] bg-[var(--c-surface)] overflow-hidden transition-colors hover:border-[var(--c-accent)]">
      <Button
        type="button"
        variant="ghost"
        onClick={(e) => {
          e.stopPropagation()
          void handleDelete()
        }}
        aria-label={`删除${displayName}`}
        className="absolute top-1.5 right-1.5 z-10 h-auto px-1.5 py-0.5 text-xs text-red-500 hover:text-red-700 bg-[var(--c-surface)]/90 hover:bg-[var(--c-surface)]"
      >
        删除
      </Button>

      <button
        type="button"
        onClick={onOpen}
        aria-label={`查看${displayName}详情`}
        className="flex h-full w-full flex-col text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--c-focus-ring)]"
      >
        {showPortrait && portraitUrl && (
          <img
            src={portraitUrl}
            alt=""
            className="absolute inset-0 h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.02]"
            onError={() => setPortraitFailed(true)}
          />
        )}

        {generating && (
          <div className="absolute inset-0 flex items-center justify-center bg-[var(--c-surface-muted)]/80" role="status" aria-busy="true">
            <div className="flex items-center gap-1.5 text-xs text-[var(--c-text-secondary)]">
              <Loader2 size={14} className="animate-spin" aria-hidden />
              生成中…
            </div>
          </div>
        )}

        <div
          className={
            showBackdrop
              ? 'relative mt-auto space-y-1 bg-gradient-to-t from-black/80 to-transparent p-3 pt-8'
              : 'space-y-2 p-3.5'
          }
        >
          <h3 className={`text-sm font-semibold leading-snug pr-8 ${showBackdrop ? 'text-white' : 'text-[var(--c-text)]'}`}>
            {displayName}
          </h3>
          <CastCharacterTags character={character} />
        </div>
      </button>

      {generationStatus === 'failed' ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={(e) => void handleRegenerate(e)}
          className="absolute bottom-2 right-2 z-10 h-auto gap-1 px-2 py-1 text-xs bg-[var(--c-surface)]/90"
        >
          <RefreshCw size={12} />
          重新生成
        </Button>
      ) : !generating && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={(e) => void handleRegenerate(e)}
          className="absolute bottom-2 right-2 z-10 h-auto gap-1 px-2 py-1 text-xs bg-[var(--c-surface)]/90 opacity-0 group-hover:opacity-100 transition-opacity"
        >
          <RefreshCw size={12} />
          {showPortrait ? '重新生成' : '生成立绘'}
        </Button>
      )}
    </div>
  )
}
