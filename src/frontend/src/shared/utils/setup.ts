import type { SetupWorld, CastCharacter, CastCharacterInput, PlotChapter, RelationshipGraph, CustomFieldSpec } from '@/shared/types'
import { sortCharactersByName } from '@/shared/utils/sortCharactersByName'

export async function fetchWorld(): Promise<SetupWorld> {
  const res = await fetch('/api/setup/world')
  const body = await res.json().catch(() => ({}))
  return { world_bible: body.world_bible ?? null }
}

export async function fetchRelationshipGraph(): Promise<RelationshipGraph> {
  const res = await fetch('/api/setup/relationship-graph')
  const body = await res.json().catch(() => ({}))
  return body.graph ?? { groups: {}, edges: {} }
}

export async function fetchCast(): Promise<CastCharacter[]> {
  const res = await fetch('/api/setup/cast')
  const body = await res.json().catch(() => ({}))
  return sortCharactersByName(body.characters ?? [])
}

export async function fetchPlot(): Promise<PlotChapter[]> {
  const res = await fetch('/api/setup/plot')
  const body = await res.json().catch(() => ({}))
  const chapters: PlotChapter[] = body.chapters ?? []
  return [...chapters].sort((a, b) => a.chapter - b.chapter)
}

export async function fetchCustomFields(): Promise<CustomFieldSpec[]> {
  const res = await fetch('/api/custom-fields')
  const body = await res.json().catch(() => ({}))
  return body.fields ?? []
}

async function parseMutationResponse<T extends object>(res: Response): Promise<
  ({ ok: true } & T) | { ok: false; error: string }
> {
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body.ok === false) {
    return { ok: false, error: body.error ?? `请求失败 (HTTP ${res.status})` }
  }
  return { ok: true, ...body } as { ok: true } & T
}

export async function patchWorldField(
  field: string,
  value: unknown,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const res = await fetch('/api/setup/world', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ field, value }),
  })
  return parseMutationResponse(res)
}

export async function addCastCharacter(
  fields: CastCharacterInput,
): Promise<{ ok: true; character: CastCharacter } | { ok: false; error: string }> {
  const res = await fetch('/api/setup/cast', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  })
  return parseMutationResponse(res)
}

export async function patchCastCharacter(
  name: string,
  fields: CastCharacterInput,
): Promise<{ ok: true; character: CastCharacter } | { ok: false; error: string }> {
  const res = await fetch(`/api/setup/cast/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  })
  return parseMutationResponse(res)
}

export async function deleteCastCharacter(
  name: string,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const res = await fetch(`/api/setup/cast/${encodeURIComponent(name)}`, { method: 'DELETE' })
  return parseMutationResponse(res)
}

export async function patchPlotChapterMeta(
  chapter: number,
  patch: { title?: string; core_xp?: string[] },
): Promise<{ ok: true } | { ok: false; error: string }> {
  const res = await fetch(`/api/setup/plot/${chapter}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  return parseMutationResponse(res)
}

export type SetupChatMsg = {
  id: string
  role: 'user' | 'assistant' | 'system' | 'choice'
  content: string
  thinking?: string
  options?: string[]
}

export type ChatEvent =
  | { type: 'setup_chat_token'; delta: string }
  | { type: 'setup_chat_tool'; name: string; phase: 'start' | 'end' | 'progress'; step?: string; label?: string }
  | { type: 'setup_chat_final'; content: string; thinking?: string }
  | { type: 'setup_chat_done' }
  | { type: 'setup_chat_choice'; question: string; options: string[] }
  | { type: 'setup_chat_error'; error: string }
  | { type: 'setup_chat_notice'; content: string; persist?: boolean }
  | { type: 'setup_chat_turn_cancelled'; rollback_failed: boolean }

export type SetupChatLiveRound = { instruction: string; events: ChatEvent[] }

export type SetupChatHistory = { messages: SetupChatMsg[]; liveRound: SetupChatLiveRound | null }

const MEMORY_HEADER = '## 已确立的设定决策（务必延续，勿与之矛盾）'

/** Aligned with backend memory.strip_memory_for_display: remove long-term memory blocks for model retelling.*/
export function stripMemoryForDisplay(content: string): string {
  if (!content.includes(MEMORY_HEADER)) return content
  const lines = content.split('\n')
  let i = 0
  if (lines[0]?.trim().startsWith('## 已确立的设定决策')) {
    i = 1
    while (i < lines.length && (lines[i].trim() === '' || lines[i].trim().startsWith('- '))) {
      i += 1
    }
  }
  return lines.slice(i).join('\n').trimStart()
}

export async function fetchSetupChatHistory(novelId: string): Promise<SetupChatHistory> {
  const qs = `?novel_id=${encodeURIComponent(novelId)}`
  const res = await fetch(`/api/setup-chat/history${qs}`)
  const body = await res.json().catch(() => ({}))
  const raw = (body.messages ?? []) as Array<Partial<SetupChatMsg> & Pick<SetupChatMsg, 'role' | 'content'>>
  const messages = raw.map((m, i) => ({
    id: m.id ?? `remote-${i}`,
    role: m.role,
    content: m.content,
    ...(m.thinking ? { thinking: m.thinking } : {}),
    ...(Array.isArray(m.options) ? { options: m.options } : {}),
  }))
  const rawLive = (body as { live_round?: unknown }).live_round
  const liveRound: SetupChatLiveRound | null = rawLive && typeof rawLive === 'object'
    ? {
        instruction: (rawLive as { instruction?: string }).instruction ?? '',
        events: Array.isArray((rawLive as { events?: unknown[] }).events)
          ? (rawLive as { events: ChatEvent[] }).events
          : [],
      }
    : null
  return { messages, liveRound }
}

export type SetupSkill = { name: string; description: string; kind: string; source: string }

/** Slash-command menu: input must be `/` + optional prefix with no trailing space yet. */
export function filterSlashMenu(input: string, skills: SetupSkill[]): SetupSkill[] | null {
  const m = /^\/([A-Za-z0-9_-]*)$/.exec(input)
  if (!m) return null
  const prefix = m[1].toLowerCase()
  return skills.filter((s) => s.name.toLowerCase().startsWith(prefix))
}

export function plotExtensionSkills(skills: SetupSkill[]): SetupSkill[] {
  return skills.filter((s) => s.kind === 'plot-extension')
}

export async function fetchSetupSkills(): Promise<SetupSkill[]> {
  const res = await fetch('/api/setup-chat/skills')
  const body = await res.json().catch(() => ({}))
  return body.skills ?? []
}

export type SetupChatAttachment = {
  attachment_id: string
  filename: string
  status?: 'processing' | 'ready' | 'error'
  error?: string
}

const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp'] as const

export function isImageAttachmentFilename(filename: string): boolean {
  const lower = filename.toLowerCase()
  return IMAGE_EXTENSIONS.some((ext) => lower.endsWith(ext))
}

export async function fetchSetupChatAttachmentStatus(
  attachmentId: string,
): Promise<{ status: 'processing' | 'ready' | 'error'; error?: string } | null> {
  const res = await fetch(`/api/setup-chat/attachments/${encodeURIComponent(attachmentId)}/status`)
  if (!res.ok) return null
  const body = await res.json().catch(() => ({}))
  const status = body.status as string | undefined
  if (status === 'processing' || status === 'ready' || status === 'error') {
    return { status, ...(typeof body.error === 'string' ? { error: body.error } : {}) }
  }
  return null
}

export async function fetchSetupChatStatus(novelId?: string): Promise<{
  busy: boolean
  imageRecognitionConfigured: boolean
}> {
  const qs = novelId ? `?novel_id=${encodeURIComponent(novelId)}` : ''
  const res = await fetch(`/api/setup-chat/status${qs}`)
  const body = await res.json().catch(() => ({}))
  return {
    busy: Boolean(body.busy),
    imageRecognitionConfigured: Boolean(body.image_recognition_configured),
  }
}

export async function uploadSetupChatAttachment(
  file: File,
): Promise<
  | { ok: true; attachment: SetupChatAttachment; warning?: string }
  | { ok: false; error: string }
> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/setup-chat/attachments', { method: 'POST', body: form })
  const body = await res.json().catch(() => ({}))
  if (!res.ok || !body.ok) {
    return { ok: false, error: body.error ?? `上传失败 (HTTP ${res.status})` }
  }
  const result: { ok: true; attachment: SetupChatAttachment; warning?: string } = {
    ok: true,
    attachment: {
      attachment_id: body.attachment_id,
      filename: body.filename,
      status: body.status === 'processing' ? 'processing' : 'ready',
    },
  }
  if (typeof body.warning === 'string') {
    result.warning = body.warning
  }
  return result
}

export async function deleteSetupChatAttachment(attachmentId: string): Promise<void> {
  await fetch(`/api/setup-chat/attachments/${attachmentId}`, { method: 'DELETE' })
}

export interface PersistedAttachmentMeta {
  attachment_id: string
  filename: string
  kind: 'image' | 'text'
  size_bytes: number
  uploaded_at: string
  has_description: boolean
}

export async function fetchAttachmentLibrary(): Promise<PersistedAttachmentMeta[]> {
  const res = await fetch('/api/setup-chat/attachments/library')
  const body = await res.json().catch(() => ({}))
  if (!res.ok || !body.ok) return []
  return body.attachments ?? []
}

export interface AttachmentParsedContent {
  attachment_id: string
  filename: string
  kind: 'image' | 'text'
  content: string | null
  has_content: boolean
}

export async function fetchAttachmentParsedContent(
  attachmentId: string,
): Promise<AttachmentParsedContent | null> {
  const res = await fetch(`/api/setup-chat/attachments/${encodeURIComponent(attachmentId)}/parsed`)
  if (!res.ok) return null
  const body = await res.json().catch(() => ({}))
  if (!body.ok) return null
  return body as AttachmentParsedContent
}

export function attachmentFileUrl(attachmentId: string): string {
  return `/api/setup-chat/attachments/${encodeURIComponent(attachmentId)}/file`
}
