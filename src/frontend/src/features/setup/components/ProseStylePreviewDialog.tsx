import type { Components } from 'react-markdown'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useProseStylePresetContent } from '@/features/setup/queries/proseStyle'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'

const components: Components = {
  h1: ({ children }) => (
    <h1 className="text-base font-semibold text-[color:var(--c-text)] mb-2">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-sm font-semibold text-[color:var(--c-text-secondary)] mt-4 mb-1.5 first:mt-0">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-xs font-semibold text-[color:var(--c-text-muted)] mt-3 mb-1">{children}</h3>
  ),
  p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="list-disc pl-5 mb-2 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 space-y-1">{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-[color:var(--c-text)]">{children}</strong>,
  hr: () => <hr className="my-3 border-[var(--c-border)]" />,
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-[var(--c-tag-violet-border)] pl-3 my-2 text-[color:var(--c-text-muted)] italic">
      {children}
    </blockquote>
  ),
}

export default function ProseStylePreviewDialog({
  presetId, title, onClose,
}: { presetId: string; title: string; onClose: () => void }) {
  const { data, isLoading } = useProseStylePresetContent(presetId, true)

  return (
    <Dialog open onOpenChange={(next) => { if (!next) onClose() }}>
      <DialogContent className="max-w-lg max-h-[80vh] flex flex-col overflow-hidden p-0">
        <DialogHeader className="px-6 py-4 border-b border-[var(--c-border-subtle)] shrink-0">
          <DialogTitle className="text-sm font-semibold">文风预览</DialogTitle>
          <p className="text-xs text-[color:var(--c-text-faint)] mt-0.5">{title}</p>
        </DialogHeader>
        <div className="px-6 py-4 overflow-y-auto text-sm text-[color:var(--c-text-secondary)]">
          {isLoading && <p className="text-xs text-[color:var(--c-text-faint)]">加载中…</p>}
          {!isLoading && !data && <p className="text-xs text-red-500">无法加载文风内容</p>}
          {!isLoading && data && (
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
              {data.content}
            </ReactMarkdown>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
