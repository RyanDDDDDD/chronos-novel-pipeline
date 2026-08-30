import { Dialog, DialogContent, DialogTitle } from '@/shared/components/ui/dialog'

interface Props {
  src: string
  alt: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Click-to-zoom overlay for a character portrait. Radix Dialog gives us the focus trap,
 * Esc-to-close and overlay-click-to-close for free; the content is stripped to just the
 * image (no panel chrome) so nothing crops it -- object-contain within the viewport. */
export default function PortraitLightbox({ src, alt, open, onOpenChange }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton
        className="w-auto max-w-[calc(100%-2rem)] border-none bg-transparent p-0 shadow-none sm:max-w-none"
      >
        <DialogTitle className="sr-only">{alt}</DialogTitle>
        <img
          src={src}
          alt={alt}
          className="max-h-[85vh] w-auto max-w-full rounded-lg object-contain"
        />
      </DialogContent>
    </Dialog>
  )
}
