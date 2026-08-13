import { RotateCcw } from 'lucide-react'
import { Button } from '@/shared/components/ui/button'

/** Retry control for failed chat assistant bubbles. */
export default function RegenerateButton({
  onClick,
  disabled = false,
  className = '',
}: {
  onClick: () => void
  disabled?: boolean
  className?: string
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label="重新生成"
      title="重新生成"
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
      className={`h-auto w-auto p-1 transition-opacity ${className}`}
    >
      <RotateCcw size={14} aria-hidden />
    </Button>
  )
}
