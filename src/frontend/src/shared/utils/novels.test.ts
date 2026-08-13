import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  listProseStyles,
  getProseStyle,
  setProseStyle,
  filterNovelsByName,
} from './novels'

afterEach(() => vi.restoreAllMocks())

describe('filterNovelsByName', () => {
  const novels = [
    { id: 'a', name: '甲小说', active: true },
    { id: 'b', name: 'Another Novel', active: false },
  ]

  it('空查询返回全部', () => {
    expect(filterNovelsByName(novels, '')).toEqual(novels)
    expect(filterNovelsByName(novels, '   ')).toEqual(novels)
  })

  it('按名称子串过滤（不区分大小写）', () => {
    expect(filterNovelsByName(novels, '甲').map((n) => n.name)).toEqual(['甲小说'])
    expect(filterNovelsByName(novels, 'novel').map((n) => n.name)).toEqual(['Another Novel'])
  })
})

describe('novels prose style API', () => {
  it('listProseStyles 解析 styles 列表', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        styles: [{ id: 'plain-direct', title: '语感调色：大白话直白体' }],
      }),
    }))
    const out = await listProseStyles()
    expect(out).toEqual([{ id: 'plain-direct', title: '语感调色：大白话直白体' }])
  })

  it('getProseStyle 解析 preset 与 addendum', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ preset: 'cold-restrained', custom_addendum: '更冷' }),
    }))
    expect(await getProseStyle('default')).toEqual({
      preset: 'cold-restrained',
      custom_addendum: '更冷',
    })
  })

  it('setProseStyle PUT 往返', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const r = await setProseStyle('default', { preset: 'cinematic', custom_addendum: '镜头感' })
    expect(r).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/novels/default/prose-style',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ preset: 'cinematic', custom_addendum: '镜头感' }),
      }),
    )
  })
})
