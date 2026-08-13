export interface Novel {
  id: string
  name: string
  active: boolean
}

export function filterNovelsByName(novels: Novel[], query: string): Novel[] {
  const q = query.trim().toLowerCase()
  if (!q) return novels
  return novels.filter((n) => n.name.toLowerCase().includes(q))
}

export interface ProseStylePreset {
  id: string
  title: string
}

export interface ProseStyleConfig {
  preset: string
  custom_addendum: string
}

export interface ProseStylePresetContent {
  id: string
  content: string
}

export async function fetchNovels(): Promise<Novel[]> {
  const res = await fetch('/api/novels')
  const body = await res.json().catch(() => ({}))
  return body.novels ?? []
}

export async function createNovel(
  name: string,
  clone = false,
): Promise<{ ok: boolean; id?: string; error?: string }> {
  const res = await fetch('/api/novels', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, clone }),
  })
  return res.json().catch(() => ({ ok: false, error: '请求失败' }))
}

export async function switchNovel(id: string): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch('/api/novels/active', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  })
  return res.json().catch(() => ({ ok: false, error: '请求失败' }))
}

export async function copyNovel(
  id: string,
  name?: string,
): Promise<{ ok: boolean; id?: string; error?: string }> {
  const res = await fetch(`/api/novels/${id}/copy`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(name ? { name } : {}),
  })
  return res.json().catch(() => ({ ok: false, error: '请求失败' }))
}

export async function renameNovel(id: string, name: string): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`/api/novels/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  return res.json().catch(() => ({ ok: false, error: '请求失败' }))
}

export async function deleteNovel(id: string): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`/api/novels/${id}`, { method: 'DELETE' })
  return res.json().catch(() => ({ ok: false, error: '请求失败' }))
}

export async function listProseStyles(): Promise<ProseStylePreset[]> {
  const res = await fetch('/api/prose-styles')
  const body = await res.json().catch(() => ({}))
  return body.styles ?? []
}

export async function getProseStylePresetContent(presetId: string): Promise<ProseStylePresetContent | null> {
  const res = await fetch(`/api/prose-styles/${presetId}`)
  if (!res.ok) return null
  const body = await res.json().catch(() => ({}))
  return typeof body.content === 'string' ? { id: presetId, content: body.content } : null
}

export async function getProseStyle(id: string): Promise<ProseStyleConfig> {
  const res = await fetch(`/api/novels/${id}/prose-style`)
  const body = await res.json().catch(() => ({}))
  return {
    preset: body.preset ?? 'plain-direct',
    custom_addendum: body.custom_addendum ?? '',
  }
}

export async function setProseStyle(
  id: string,
  config: ProseStyleConfig,
): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`/api/novels/${id}/prose-style`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  return res.json().catch(() => ({ ok: false, error: '请求失败' }))
}

import type { StateDeriveFieldSpec } from '@/shared/types'

export async function listStateDeriveFields(): Promise<StateDeriveFieldSpec[]> {
  const res = await fetch('/api/state-derive-fields')
  const body = await res.json().catch(() => ({}))
  return Array.isArray(body.fields) ? body.fields : []
}

export async function getSandboxDialogueTurnCount(id: string): Promise<number | null> {
  const res = await fetch(`/api/novels/${id}/sandbox-dialogue-turn-count`)
  const body = await res.json().catch(() => ({}))
  return typeof body.turn_count === 'number' ? body.turn_count : null
}

export async function setSandboxDialogueTurnCount(
  id: string,
  turnCount: number | null,
): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`/api/novels/${id}/sandbox-dialogue-turn-count`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ turn_count: turnCount }),
  })
  return res.json().catch(() => ({ ok: false, error: '请求失败' }))
}
