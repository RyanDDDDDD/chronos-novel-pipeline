import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { FileText, ImageIcon, RefreshCw } from 'lucide-react'
import EmptyStateCard from '@/shared/components/EmptyStateCard'
import { Button } from '@/shared/components/ui/button'
import { useActiveNovelId } from '@/shared/queries/novels'
import { setupKey } from '@/shared/queries/keys'
import {
  useAttachmentLibrary,
  useAttachmentParsedContent,
  type PersistedAttachmentMeta,
} from '@/shared/queries/attachments'
import { attachmentFileUrl } from '@/shared/utils/setup'

type KindFilter = 'all' | 'image' | 'text'

function formatUploadedAt(iso: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function statusLabel(item: PersistedAttachmentMeta): string {
  if (item.kind === 'image') return item.has_description ? '已解析' : '待识别'
  return '原文'
}

function statusClass(item: PersistedAttachmentMeta): string {
  if (item.kind === 'image' && !item.has_description) {
    return 'bg-amber-50 text-amber-700 border-amber-200'
  }
  if (item.has_description || item.kind === 'text') {
    return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  }
  return 'bg-[var(--c-surface-muted)] text-[var(--c-text-muted)] border-[var(--c-border)]'
}

function AttachmentListItem({
  item,
  selected,
  onSelect,
}: {
  item: PersistedAttachmentMeta
  selected: boolean
  onSelect: () => void
}) {
  const Icon = item.kind === 'image' ? ImageIcon : FileText
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full text-left rounded-lg border px-3 py-2 transition-colors ${
        selected
          ? 'border-[var(--c-accent)] bg-[var(--c-accent-subtle)]'
          : 'border-[var(--c-border)] bg-[var(--c-surface)] hover:bg-[var(--c-surface-hover)]'
      }`}
    >
      <div className="flex items-start gap-2 min-w-0">
        <Icon size={16} className="shrink-0 mt-0.5 text-[var(--c-text-muted)]" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-[var(--c-text)] truncate">{item.filename}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--c-text-muted)]">
            <span>{formatSize(item.size_bytes)}</span>
            {item.uploaded_at && <span>{formatUploadedAt(item.uploaded_at)}</span>}
          </div>
          <span className={`inline-block mt-1.5 rounded-md border px-1.5 py-0.5 text-[11px] ${statusClass(item)}`}>
            {statusLabel(item)}
          </span>
        </div>
      </div>
    </button>
  )
}

function AttachmentDetail({ item }: { item: PersistedAttachmentMeta }) {
  const { data, isLoading } = useAttachmentParsedContent(item.attachment_id)

  return (
    <div className="flex flex-col gap-4 min-h-0">
      <div>
        <h3 className="text-sm font-semibold text-[var(--c-text)]">{item.filename}</h3>
        <p className="text-xs text-[var(--c-text-muted)] mt-1">
          {item.kind === 'image' ? '图片附件' : '文本附件'}
          {' · '}
          {formatSize(item.size_bytes)}
          {item.uploaded_at ? ` · ${formatUploadedAt(item.uploaded_at)}` : ''}
        </p>
      </div>

      {item.kind === 'image' && (
        <div className="rounded-lg border border-[var(--c-border)] bg-[var(--c-surface-muted)] p-2">
          <img
            src={attachmentFileUrl(item.attachment_id)}
            alt={item.filename}
            className="max-h-80 w-full object-contain rounded-md"
          />
        </div>
      )}

      <section className="min-h-0 flex-1 flex flex-col">
        <h4 className="text-xs font-medium text-[var(--c-text-muted)] mb-2">
          {item.kind === 'image' ? '识别解析内容' : '文件内容'}
        </h4>
        {isLoading ? (
          <p className="text-sm text-[var(--c-text-muted)]">加载中…</p>
        ) : data?.has_content && data.content ? (
          <pre className="flex-1 min-h-[12rem] overflow-auto rounded-lg border border-[var(--c-border)] bg-[var(--c-surface)] p-3 text-sm text-[var(--c-text)] whitespace-pre-wrap leading-relaxed">
            {data.content}
          </pre>
        ) : (
          <p className="text-sm text-[var(--c-text-muted)] rounded-lg border border-dashed border-[var(--c-border)] p-4">
            {item.kind === 'image'
              ? '尚无解析结果。请在「对话」页上传图片并让共创者调用 read_attachment_image 完成识别。'
              : '无法读取文件内容。'}
          </p>
        )}
      </section>
    </div>
  )
}

export default function AttachmentsTab() {
  const novelId = useActiveNovelId()
  const queryClient = useQueryClient()
  const { data: attachments = [], isLoading, isFetching } = useAttachmentLibrary()
  const [filter, setFilter] = useState<KindFilter>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const filtered = useMemo(() => {
    if (filter === 'all') return attachments
    return attachments.filter((a) => a.kind === filter)
  }, [attachments, filter])

  useEffect(() => {
    if (filtered.length === 0) {
      setSelectedId(null)
      return
    }
    if (!selectedId || !filtered.some((a) => a.attachment_id === selectedId)) {
      setSelectedId(filtered[0].attachment_id)
    }
  }, [filtered, selectedId])

  const selected = filtered.find((a) => a.attachment_id === selectedId) ?? null

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: setupKey('attachments', novelId) })
  }

  const filterBtn = (kind: KindFilter, label: string) => (
    <button
      key={kind}
      type="button"
      onClick={() => setFilter(kind)}
      className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
        filter === kind
          ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)]'
          : 'text-[var(--c-text-muted)] hover:bg-[var(--c-surface-hover)]'
      }`}
    >
      {label}
    </button>
  )

  return (
    <div className="flex flex-1 min-h-0 flex-col gap-3 overflow-hidden">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          {filterBtn('all', '全部')}
          {filterBtn('image', '图片')}
          {filterBtn('text', '文本')}
        </div>
        <Button type="button" variant="outline" size="sm" onClick={refresh} disabled={isFetching}>
          <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} aria-hidden />
          刷新
        </Button>
      </div>

      {isLoading ? (
        <p className="text-sm text-[var(--c-text-muted)]">加载附件列表…</p>
      ) : filtered.length === 0 ? (
        <EmptyStateCard
          icon={ImageIcon}
          message={
            filter === 'image'
              ? '尚无图片附件。去「对话」页上传图片，识别完成后会出现在这里。'
              : '尚无已保存的附件。在「对话」页上传图片或文本文件后会持久化到此处。'
          }
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden lg:grid lg:grid-cols-[minmax(220px,280px)_1fr] lg:grid-rows-1">
          <div
            className="flex max-h-[min(40vh,320px)] min-h-0 flex-col gap-2 overflow-y-auto pr-1 lg:max-h-none lg:h-full"
            aria-label="附件列表"
          >
            {filtered.map((item) => (
              <AttachmentListItem
                key={item.attachment_id}
                item={item}
                selected={item.attachment_id === selectedId}
                onSelect={() => setSelectedId(item.attachment_id)}
              />
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-[var(--c-border)] bg-[var(--c-surface)] p-4">
            {selected ? <AttachmentDetail item={selected} /> : null}
          </div>
        </div>
      )}
    </div>
  )
}
