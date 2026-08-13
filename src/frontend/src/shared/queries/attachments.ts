import { useQuery } from '@tanstack/react-query'
import { setupKey } from '@/shared/queries/keys'
import { useActiveNovelId } from '@/shared/queries/novels'
import {
  fetchAttachmentLibrary,
  fetchAttachmentParsedContent,
  type PersistedAttachmentMeta,
} from '@/shared/utils/setup'

export function useAttachmentLibrary() {
  const novelId = useActiveNovelId()
  return useQuery({
    queryKey: setupKey('attachments', novelId),
    queryFn: fetchAttachmentLibrary,
    enabled: !!novelId,
  })
}

export function useAttachmentParsedContent(attachmentId: string | null) {
  const novelId = useActiveNovelId()
  return useQuery({
    queryKey: [...setupKey('attachments', novelId), 'parsed', attachmentId] as const,
    queryFn: () => fetchAttachmentParsedContent(attachmentId!),
    enabled: !!novelId && !!attachmentId,
  })
}

export type { PersistedAttachmentMeta }
