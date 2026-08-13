import { describe, it, expect } from 'vitest'
import { resolveNovelSwitch, viewFromPathname, setupTabFromPathname, workflowTabFromSearch } from '@/shared/utils/novelRoute'
import type { Novel } from '@/shared/utils/novels'

const novels: Novel[] = [
  { id: 'a', name: 'A', active: false },
  { id: 'b', name: 'B', active: true },
]

describe('resolveNovelSwitch', () => {
  it('id 等于后端 active → none', () => {
    expect(resolveNovelSwitch('b', novels)).toEqual({ action: 'none' })
  })
  it('id 合法但非 active → switch 到该 id', () => {
    expect(resolveNovelSwitch('a', novels)).toEqual({ action: 'switch', target: 'a' })
  })
  it('id 非法 → redirect 回 active', () => {
    expect(resolveNovelSwitch('zzz', novels)).toEqual({ action: 'redirect', target: 'b' })
  })
  it('id 为空 → redirect 回 active', () => {
    expect(resolveNovelSwitch(undefined, novels)).toEqual({ action: 'redirect', target: 'b' })
  })
  it('无 active 但有小说 → redirect 回首个', () => {
    const noActive: Novel[] = [{ id: 'a', name: 'A', active: false }]
    expect(resolveNovelSwitch('zzz', noActive)).toEqual({ action: 'redirect', target: 'a' })
  })
  it('空列表 → none（等加载）', () => {
    expect(resolveNovelSwitch('a', [])).toEqual({ action: 'none' })
  })
})

describe('viewFromPathname', () => {
  it('从 /novel/:id/<view> 取 view', () => {
    expect(viewFromPathname('/novel/abc/setup')).toBe('setup')
    expect(viewFromPathname('/novel/abc/chat')).toBe('chat')
    expect(viewFromPathname('/novel/abc/sandbox')).toBe('sandbox')
    expect(viewFromPathname('/novel/abc/author')).toBe('author')
    expect(viewFromPathname('/novel/abc/manuscript')).toBe('manuscript')
  })
  it('无 view 段或非法 → 落 pipeline', () => {
    expect(viewFromPathname('/novel/abc')).toBe('pipeline')
    expect(viewFromPathname('/novel/abc/zzz')).toBe('pipeline')
  })
})

describe('setupTabFromPathname', () => {
  it('/setup/<tab> 段取出合法子页', () => {
    expect(setupTabFromPathname('/novel/abc/setup/world')).toBe('world')
    expect(setupTabFromPathname('/novel/abc/setup/cast')).toBe('cast')
    expect(setupTabFromPathname('/novel/abc/setup/plot')).toBe('plot')
    expect(setupTabFromPathname('/novel/abc/setup/archives')).toBe('archives')
    expect(setupTabFromPathname('/novel/abc/setup/attachments')).toBe('attachments')
  })
  it('非法子页或缺失 → null', () => {
    expect(setupTabFromPathname('/novel/abc/setup')).toBeNull()
    expect(setupTabFromPathname('/novel/abc/setup/zzz')).toBeNull()
  })
  it('不在 /setup 下 → null', () => {
    expect(setupTabFromPathname('/novel/abc/chat')).toBeNull()
    expect(setupTabFromPathname('/novel/abc')).toBeNull()
  })
})

describe('workflowTabFromSearch', () => {
  it('合法 ?tab= 取值', () => {
    expect(workflowTabFromSearch('?tab=skeleton')).toBe('skeleton')
    expect(workflowTabFromSearch('?tab=runtime')).toBe('runtime')
    expect(workflowTabFromSearch('?tab=sandbox')).toBe('sandbox')
  })
  it('非法或缺失 → runtime', () => {
    expect(workflowTabFromSearch('')).toBe('runtime')
    expect(workflowTabFromSearch('?tab=zzz')).toBe('runtime')
  })
})
