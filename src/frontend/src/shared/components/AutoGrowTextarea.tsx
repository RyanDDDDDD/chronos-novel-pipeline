import { useEffect, useRef, type TextareaHTMLAttributes } from 'react'
import { resizeTextareaToFit } from '@/shared/components/ChatComposerInput'
import { Textarea } from '@/shared/components/ui/textarea'

interface Props extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  minPx?: number
  maxPx?: number
}

/** Plain textarea that grows with its content instead of clipping past `rows` with a
 * near-invisible scrollbar (see resizeTextareaToFit) -- for one-shot setup/config fields
 * that aren't the chat composer. */
export default function AutoGrowTextarea({ minPx = 40, maxPx = 320, value, ...rest }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = ref.current
    if (el) resizeTextareaToFit(el, minPx, maxPx)
  }, [value, minPx, maxPx])

  return <Textarea ref={ref} value={value} {...rest} />
}
