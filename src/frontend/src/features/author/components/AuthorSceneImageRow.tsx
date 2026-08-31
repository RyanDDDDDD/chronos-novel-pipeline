import { useSelector } from 'react-redux'
import { Image as ImageIcon, Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/shared/components/ui/button'
import { selectAuthorSceneImageStatus } from '@/shared/store/authorSceneImageSlice'
import type { RootState } from '@/shared/store/store'

/** Per-stage scene-image control on the main-writer synthesis bubble: a 生图 button when
 * nothing exists, or the inline image + a 重新生成 button once one does. Generation runs
 * server-side behind the shared image-gen gate; this component only fires the request and
 * reflects the WS status folded into authorSceneImageSlice. */
export default function AuthorSceneImageRow({
  chapter, index, imageUrl, onGenerate,
}: {
  chapter: number
  index: number
  imageUrl?: string
  onGenerate: () => void
}) {
  const status = useSelector(
    (s: RootState) => selectAuthorSceneImageStatus(s, chapter, index),
  )
  const generating = status === 'generating'
  const failed = status === 'failed'

  if (imageUrl) {
    return (
      <div className="mt-2 space-y-1">
        <img
          src={imageUrl}
          alt="场景插画"
          className="max-w-full rounded-lg border border-[var(--c-border)]"
        />
        <Button
          type="button"
          variant="ghost"
          size="xs"
          disabled={generating}
          onClick={onGenerate}
          className="text-[var(--c-text-muted)]"
        >
          {generating
            ? <Loader2 className="animate-spin" aria-hidden />
            : <RefreshCw aria-hidden />}
          {generating ? '生图中…' : '重新生成'}
        </Button>
      </div>
    )
  }

  return (
    <div className="mt-2 space-y-1">
      <Button
        type="button"
        variant="outline"
        size="xs"
        disabled={generating}
        onClick={onGenerate}
      >
        {generating
          ? <Loader2 className="animate-spin" aria-hidden />
          : <ImageIcon aria-hidden />}
        {generating ? '生图中…' : '生图'}
      </Button>
      {failed && (
        <p className="text-[11px] text-red-500">场景生图失败，可重试</p>
      )}
    </div>
  )
}
