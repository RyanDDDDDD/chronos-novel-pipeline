import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { Button } from '@/shared/components/ui/button'

/** Hover-revealed copy-to-clipboard icon for chat bubbles. Copies the raw text passed in
 * (markdown source, not rendered plain text) -- callers own visibility/positioning via
 * className (typically `opacity-0 group-hover:opacity-100` on a `group relative` ancestor). */
export default function CopyButton({ text, className = '' }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false)

  const handleClick = async (e: React.MouseEvent) => {
    e.stopPropagation()
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label={copied ? '已复制' : '复制'}
      title={copied ? '已复制' : '复制'}
      onClick={(e) => void handleClick(e)}
      className={`h-auto w-auto p-1 transition-opacity ${className}`}
    >
      {copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
    </Button>
  )
}
