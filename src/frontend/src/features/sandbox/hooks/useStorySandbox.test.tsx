import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useStorySandbox } from './useStorySandbox'

describe('useStorySandbox', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('sendMessage posts chapter+branch_id+text and returns ok on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true, status: 'running' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.sendMessage(3, 'b1', '继续')
    expect(res).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith('/api/story-sandbox/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter: 3, branch_id: 'b1', text: '继续' }),
    })
  })

  it('sendMessage surfaces backend error message on non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 409, json: async () => ({ ok: false, error: '上一轮还在进行' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.sendMessage(3, 'b1', '继续')
    expect(res).toEqual({ ok: false, error: '上一轮还在进行' })
  })

  it('fetchHistory GETs with chapter/branch query params and returns rounds', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        rounds: [{
          instruction: '继续', prose: '他抬起头。',
          character_states: { 甲: { personality: '平静' } }, suggestions: ['某建议'],
          initial_states: { 甲: { personality: '外冷内热' } },
          scene_state: { description: '昏暗的书房' },
          initial_scene_state: { description: '开场时的书房' },
        }],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const history = await result.current.fetchHistory(3, 'b1', 'novel-1')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/story-sandbox/history?chapter=3&branch_id=b1&novel_id=novel-1',
    )
    expect(history.rounds).toEqual([{
      instruction: '继续', prose: '他抬起头。',
      characterStates: { 甲: { personality: '平静' } }, suggestions: ['某建议'],
      initialStates: { 甲: { personality: '外冷内热' } },
      sceneState: { description: '昏暗的书房' },
      initialSceneState: { description: '开场时的书房' },
      eventLogEntries: [],
      rollingSummaryAfter: '',
      recallContext: '',
      recalledSettings: [],
      profileMutation: null,
    }])
    expect(history.active_cast).toEqual([])
  })

  it('fetchHistory defaults sceneState to {} and initialSceneState to null when the backend round has none', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        rounds: [{
          instruction: '继续', prose: '他抬起头。',
          character_states: {}, suggestions: [],
        }],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const history = await result.current.fetchHistory(3, 'b1', 'novel-1')
    expect(history.rounds[0].sceneState).toEqual({})
    expect(history.rounds[0].initialSceneState).toBeNull()
  })

  it('fetchHistory defaults initialStates to null when the backend round has none', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        rounds: [{
          instruction: '继续', prose: '他抬起头。',
          character_states: {}, suggestions: [],
        }],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const history = await result.current.fetchHistory(3, 'b1', 'novel-1')
    expect(history.rounds[0].initialStates).toBeNull()
  })

  it('fetchHistory returns empty history on backend failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    const { result } = renderHook(() => useStorySandbox())
    const history = await result.current.fetchHistory(3, 'b1', 'novel-1')
    expect(history).toEqual({ rounds: [], active_cast: [], liveRound: null })
  })

  it('stopTurn posts chapter+branch_id and returns ok on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.stopTurn(3, 'b1')
    expect(res).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith('/api/story-sandbox/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter: 3, branch_id: 'b1' }),
    })
  })

  it('stopTurn surfaces backend error message on non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 409, json: async () => ({ ok: false, error: '没有正在进行的回合' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.stopTurn(3, 'b1')
    expect(res).toEqual({ ok: false, error: '没有正在进行的回合' })
  })

  it('stopTurn returns a network error when fetch throws', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.stopTurn(3, 'b1')
    expect(res).toEqual({ ok: false, error: '无法连接后端' })
  })

  it('regenerateSuggestions posts chapter+branch_id and returns ok on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.regenerateSuggestions(3, 'b1')
    expect(res).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith('/api/story-sandbox/suggestions/regenerate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter: 3, branch_id: 'b1', hint: '' }),
    })
  })

  it('includes hint in the request body when provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    await result.current.regenerateSuggestions(1, 'b1', '往乙这边的反应上靠一点')
    const [, options] = fetchMock.mock.calls[0]
    expect(JSON.parse(options.body)).toEqual({
      chapter: 1, branch_id: 'b1', hint: '往乙这边的反应上靠一点',
    })
  })

  it('defaults hint to an empty string when omitted', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    await result.current.regenerateSuggestions(1, 'b1')
    const [, options] = fetchMock.mock.calls[0]
    expect(JSON.parse(options.body)).toEqual({ chapter: 1, branch_id: 'b1', hint: '' })
  })

  it('regenerateSuggestions surfaces backend error message on non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 409, json: async () => ({ ok: false, error: '上一轮还在进行' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.regenerateSuggestions(3, 'b1')
    expect(res).toEqual({ ok: false, error: '上一轮还在进行' })
  })

  it('startRewrite posts chapter+branch_id+feedback and returns ok on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true, status: 'running' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.startRewrite(3, 'b1', '语气再冷淡一点')
    expect(res).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith('/api/story-sandbox/rewrite', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter: 3, branch_id: 'b1', feedback: '语气再冷淡一点' }),
    })
  })

  it('startRewrite surfaces backend error message on non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 409, json: async () => ({ ok: false, error: '上一轮还在进行' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.startRewrite(3, 'b1', '反馈')
    expect(res).toEqual({ ok: false, error: '上一轮还在进行' })
  })

  it('startRewrite returns a network error when fetch throws', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.startRewrite(3, 'b1', '反馈')
    expect(res).toEqual({ ok: false, error: '无法连接后端' })
  })

  it('retryDerive posts chapter+branch_id and returns ok on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true, status: 'running' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.retryDerive(3, 'b1')
    expect(res).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith('/api/story-sandbox/retry-derive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter: 3, branch_id: 'b1' }),
    })
  })

  it('retryDerive surfaces backend error message on non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 409, json: async () => ({ ok: false, error: '没有可重试的推演失败记录，请重新输入指令' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.retryDerive(3, 'b1')
    expect(res).toEqual({ ok: false, error: '没有可重试的推演失败记录，请重新输入指令' })
  })

  it('retryDerive returns a network error when fetch throws', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.retryDerive(3, 'b1')
    expect(res).toEqual({ ok: false, error: '无法连接后端' })
  })

  it('rewriteSelection posts chapter+branch_id+original_text+anchor_offset+feedback and returns ok on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true, status: 'running' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.rewriteSelection(3, 'b1', '看向窗外', 3, '语气再冷淡一点')
    expect(res).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith('/api/story-sandbox/rewrite-selection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chapter: 3, branch_id: 'b1', original_text: '看向窗外', anchor_offset: 3,
        feedback: '语气再冷淡一点',
      }),
    })
  })

  it('rewriteSelection surfaces backend error message on non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 409, json: async () => ({ ok: false, error: '上一轮还在进行' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.rewriteSelection(3, 'b1', '看向窗外', 3, '')
    expect(res).toEqual({ ok: false, error: '上一轮还在进行' })
  })

  it('rewriteSelection returns a network error when fetch throws', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    const { result } = renderHook(() => useStorySandbox())
    const res = await result.current.rewriteSelection(3, 'b1', '看向窗外', 3, '')
    expect(res).toEqual({ ok: false, error: '无法连接后端' })
  })

  it('sendMessage includes submitted_directions in the body when provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true, status: 'running' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    await result.current.sendMessage(3, 'b1', '- 建议一', ['建议一'])
    expect(fetchMock).toHaveBeenCalledWith('/api/story-sandbox/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chapter: 3, branch_id: 'b1', text: '- 建议一', submitted_directions: ['建议一'],
      }),
    })
  })

  it('sendMessage omits submitted_directions from the body when not provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true, status: 'running' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    await result.current.sendMessage(3, 'b1', '继续')
    expect(fetchMock).toHaveBeenCalledWith('/api/story-sandbox/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter: 3, branch_id: 'b1', text: '继续' }),
    })
  })

  it('fetchHistory maps submitted_directions when present', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        rounds: [{
          instruction: '继续', prose: '他抬起头。',
          character_states: {}, suggestions: ['建议一'],
          submitted_directions: ['建议一'],
        }],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const history = await result.current.fetchHistory(3, 'b1', 'novel-1')
    expect(history.rounds[0].submittedDirections).toEqual(['建议一'])
  })

  it('fetchHistory leaves submittedDirections undefined when the backend round has none', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        rounds: [{ instruction: '继续', prose: '他抬起头。', character_states: {}, suggestions: [] }],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useStorySandbox())
    const history = await result.current.fetchHistory(3, 'b1', 'novel-1')
    expect(history.rounds[0].submittedDirections).toBeUndefined()
  })
})
