import type { ReactNode } from 'react'
import type { Components } from 'react-markdown'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { repairMarkdownTables } from '@/shared/utils/markdownTables'

const HIGHLIGHT_CLASS = 'ring-1 ring-rose-300 bg-rose-50/50 rounded-md'

/** Map ## heading text to profile_mutate / archive field keys for sandbox highlight targeting. */
const H2_FIELD_KEYS: Record<string, string> = {
  身份背景: 'identity_background',
  性格: 'personality',
  爱好: 'hobbies',
  口癖: 'verbal_tic',
  体格: 'physique',
}

function nodeText(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(nodeText).join('')
  if (typeof node === 'object' && 'props' in node && node.props) {
    return nodeText((node.props as { children?: ReactNode }).children)
  }
  return ''
}

function isHighlighted(highlightedFields: Set<string> | undefined, key: string): boolean {
  return highlightedFields?.has(key) ?? false
}

function buildComponents(highlightedFields?: Set<string>): Components {
  return {
    h1: ({ children }) => (
      <h1 className="text-lg font-semibold text-[var(--c-text)] mb-3">{children}</h1>
    ),
    h2: ({ children }) => {
      const label = nodeText(children).trim()
      const fieldKey = H2_FIELD_KEYS[label]
      const highlighted = fieldKey != null && isHighlighted(highlightedFields, fieldKey)
      return (
        <h2
          className={`text-sm font-semibold text-[var(--c-text)] mt-5 mb-2 first:mt-0 border-b border-[var(--c-border-subtle)] pb-1 ${highlighted ? HIGHLIGHT_CLASS : ''}`}
        >
          {children}
        </h2>
      )
    },
    h3: ({ children }) => {
      const text = nodeText(children).trim()
      const axis = text.split(' · ')[0]?.trim() ?? text
      const highlighted = isHighlighted(highlightedFields, `sliders:${axis}`)
      return (
        <h3
          className={`text-sm font-medium text-[var(--c-text-secondary)] mt-3 mb-1.5 ${highlighted ? HIGHLIGHT_CLASS : ''}`}
        >
          {children}
        </h3>
      )
    },
    p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
    ul: ({ children }) => <ul className="list-disc pl-5 mb-2 space-y-1">{children}</ul>,
    ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 space-y-1">{children}</ol>,
    li: ({ children }) => {
      const text = nodeText(children).trim()
      const physiqueMatch = /^\*\*(.+?)\*\*：/.exec(text)
      const highlighted =
        physiqueMatch != null && isHighlighted(highlightedFields, `physique:${physiqueMatch[1]}`)
      return (
        <li className={`leading-relaxed ${highlighted ? HIGHLIGHT_CLASS : ''}`}>{children}</li>
      )
    },
    strong: ({ children }) => <strong className="font-semibold text-[var(--c-text)]">{children}</strong>,
    hr: () => <hr className="my-4 border-[var(--c-border-subtle)]" />,
    blockquote: ({ children }) => (
      <blockquote className="border-l-2 border-[var(--c-tag-violet-border)] pl-3 my-2 text-[var(--c-text-muted)] italic">
        {children}
      </blockquote>
    ),
    img: ({ alt, src }) => (
      <div className="my-3 flex justify-center">
        <div className="w-40 aspect-[2/3] rounded-md overflow-hidden border border-[var(--c-border)] bg-[var(--c-surface-muted)]">
          <img src={src} alt={alt ?? ''} className="h-full w-full object-cover" />
        </div>
      </div>
    ),
  }
}

export function CharacterMarkdownContent({
  content,
  highlightedFields,
}: {
  content: string
  highlightedFields?: Set<string>
}) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildComponents(highlightedFields)}>
      {repairMarkdownTables(content)}
    </ReactMarkdown>
  )
}
