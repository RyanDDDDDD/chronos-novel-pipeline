import type { AnchorHTMLAttributes } from 'react'
import type { Components } from 'react-markdown'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { repairMarkdownTables } from '@/shared/utils/markdownTables'

const LINK_CLASS =
  'font-medium text-[var(--c-accent)] underline decoration-[var(--c-accent)]/70 underline-offset-2 break-all hover:text-[var(--c-accent-hover)]'

function MarkdownLink({ href, children, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  const external = typeof href === 'string' && /^https?:\/\//i.test(href)
  return (
    <a
      href={href}
      {...rest}
      {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
      className={LINK_CLASS}
    >
      {children}
    </a>
  )
}

const components: Components = {
  h3: ({ children }) => (
    <h3 className="font-semibold text-slate-800 mt-3 mb-1 first:mt-0">{children}</h3>
  ),
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="list-disc pl-5 mb-2 space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 space-y-0.5">{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  a: MarkdownLink,
  hr: () => <hr className="my-3 border-slate-200" />,
  table: ({ children }) => (
    <div className="overflow-x-auto my-2">
      <table className="min-w-full text-sm border-collapse">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead>{children}</thead>,
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => <tr>{children}</tr>,
  th: ({ children }) => (
    <th className="border border-slate-200 bg-slate-50 px-2 py-1 text-left font-medium">{children}</th>
  ),
  td: ({ children }) => <td className="border border-slate-200 px-2 py-1 align-top">{children}</td>,
}

export default function ChatMarkdown({ content }: { content: string }) {
  const repaired = repairMarkdownTables(content)
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {repaired}
    </ReactMarkdown>
  )
}
