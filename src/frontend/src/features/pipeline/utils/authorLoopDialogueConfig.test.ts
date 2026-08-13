import { describe, it, expect, vi, afterEach } from 'vitest'
import { defaultEnableThinkingForNode, fetchDialogueConfig, putDialogueConfig } from './authorLoopDialogueConfig'

afterEach(() => vi.restoreAllMocks())

describe('authorLoopDialogueConfig', () => {
  it('defaultEnableThinkingForNode: core creative nodes ON, auxiliary OFF', () => {
    expect(defaultEnableThinkingForNode('director')).toBe(true)
    expect(defaultEnableThinkingForNode('prose')).toBe(true)
    expect(defaultEnableThinkingForNode('dialogue_draft')).toBe(false)
    expect(defaultEnableThinkingForNode('dialogue')).toBe(false)
    expect(defaultEnableThinkingForNode('author_prose')).toBe(false)
    expect(defaultEnableThinkingForNode('chat_identity')).toBe(true)
    expect(defaultEnableThinkingForNode('state_derive')).toBe(false)
    expect(defaultEnableThinkingForNode('text_recognition')).toBe(false)
  })

  it('fetchDialogueConfig 解析 target_words/两组 review hook 状态列表', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({
        config: {
          target_words: 4200,
          disabled_buildtime_review_hooks: ['coherence'], disabled_runtime_review_hooks: ['fidelity'],
          disabled_setup_review_hooks: ['setup_world_completeness'],
          llm_params: {},
        },
        buildtime_review_hooks: [
          { name: 'coherence', display_name: '衔接判官', axis: 'transition', enabled: false },
        ],
        runtime_review_hooks: [
          { name: 'fidelity', display_name: '骨架保真判官', enabled: false },
        ],
        setup_review_hooks: [
          { name: 'setup_world_completeness', display_name: '世界观完整度', enabled: false },
        ],
      }),
    }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.target_words).toBe(4200)
    expect(state.config.disabled_buildtime_review_hooks).toEqual(['coherence'])
    expect(state.config.disabled_runtime_review_hooks).toEqual(['fidelity'])
    expect(state.config.disabled_setup_review_hooks).toEqual(['setup_world_completeness'])
    expect(state.config.llm_params).toEqual({})
    expect(state.config.sandbox_llm_params).toEqual({})
    expect(state.buildtime_review_hooks).toEqual([
      { name: 'coherence', display_name: '衔接判官', axis: 'transition', enabled: false },
    ])
    expect(state.runtime_review_hooks).toEqual([
      { name: 'fidelity', display_name: '骨架保真判官', enabled: false },
    ])
    expect(state.setup_review_hooks).toEqual([
      { name: 'setup_world_completeness', display_name: '世界观完整度', enabled: false },
    ])
  })

  it('fetchDialogueConfig 缺字段时降级为空数组/默认字数', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: async () => ({}) }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.target_words).toBe(3000)
    expect(state.config.disabled_buildtime_review_hooks).toEqual([])
    expect(state.config.disabled_runtime_review_hooks).toEqual([])
    expect(state.config.disabled_setup_review_hooks).toEqual([])
    expect(state.config.llm_params).toEqual({})
    expect(state.config.sandbox_llm_params).toEqual({})
    expect(state.buildtime_review_hooks).toEqual([])
    expect(state.runtime_review_hooks).toEqual([])
    expect(state.setup_review_hooks).toEqual([])
  })

  it('putDialogueConfig 提交后重新拉取最新状态', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ json: async () => ({ ok: true }) })
      .mockResolvedValueOnce({
        json: async () => ({
          config: {
            target_words: 3000,
            disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
            llm_params: {},
          },
          buildtime_review_hooks: [],
          runtime_review_hooks: [],
        }),
      })
    vi.stubGlobal('fetch', fetchMock)
    const state = await putDialogueConfig('novel-1', { dialogue: { target_words: 3000 } })
    expect(state.config.target_words).toBe(3000)
    expect(fetchMock.mock.calls[0][1]?.method).toBe('PUT')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/author-loop/dialogue-config?novel_id=novel-1')
  })

  it('fetchDialogueConfig 解析 llm_params，未知节点/字段被丢弃', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({
        config: {
          target_words: 3000,
          disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
          llm_params: {
            director: { temperature: 0.8, top_p: 0.95, logit_bias: { '1': -100 } },
            'not-a-node': { temperature: 0.5 },
          },
        },
        buildtime_review_hooks: [], runtime_review_hooks: [],
      }),
    }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.llm_params).toEqual({ director: { temperature: 0.8, top_p: 0.95 } })
  })

  it('fetchDialogueConfig 解析 sandbox_llm_params，未知节点/字段被丢弃', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({
        config: {
          target_words: 3000,
          disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
          sandbox_llm_params: {
            prose: { temperature: 0.9, top_p: 0.85, logit_bias: { '1': -100 } },
            'not-a-node': { temperature: 0.5 },
          },
        },
        buildtime_review_hooks: [], runtime_review_hooks: [],
      }),
    }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.sandbox_llm_params).toEqual({ prose: { temperature: 0.9, top_p: 0.85 } })
  })

  it('fetchDialogueConfig 解析 enable_thinking/thinking_effort，非法值被丢弃', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({
        config: {
          target_words: 3000,
          disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
          llm_params: {
            director: { temperature: 0.8, enable_thinking: true, thinking_effort: 'high' },
            review: { enable_thinking: 'yes', thinking_effort: 'extreme' },
          },
        },
        buildtime_review_hooks: [], runtime_review_hooks: [],
      }),
    }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.llm_params).toEqual({
      director: { temperature: 0.8, enable_thinking: true, thinking_effort: 'high' },
    })
  })

  it('fetchDialogueConfig 解析 provider/base_url/model，缺的那个字段被丢弃，其余独立保留', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({
        config: {
          target_words: 3000,
          disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
          sandbox_llm_params: {
            prose: { provider: 'local', base_url: 'http://localhost:1234/v1', model: 'qwen3-8b' },
            derive_char: { provider: 'local', base_url: 'http://localhost:1234/v1' },
            derive_scene: { provider: 'local', model: 'qwen3-8b' },
            summary_fold: { provider: 'local' },
            event_extract: { provider: 'local' },
          },
        },
        buildtime_review_hooks: [], runtime_review_hooks: [],
      }),
    }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.sandbox_llm_params).toEqual({
      prose: { provider: 'local', base_url: 'http://localhost:1234/v1', model: 'qwen3-8b' },
      derive_char: { provider: 'local', base_url: 'http://localhost:1234/v1' },
      derive_scene: { provider: 'local', model: 'qwen3-8b' },
      summary_fold: { provider: 'local' },
      event_extract: { provider: 'local' },
    })
  })

  it('fetchDialogueConfig：provider 为 cloud 时不落 base_url/model', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({
        config: {
          target_words: 3000,
          disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
          llm_params: {
            director: { provider: 'cloud', temperature: 0.8 },
          },
        },
        buildtime_review_hooks: [], runtime_review_hooks: [],
      }),
    }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.llm_params).toEqual({ director: { temperature: 0.8 } })
  })

  it('fetchDialogueConfig 解析 disable_style_guard，非 bool 值被丢弃', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({
        config: {
          target_words: 3000,
          disabled_buildtime_review_hooks: [], disabled_runtime_review_hooks: [],
          llm_params: {
            director: { temperature: 0.8, disable_style_guard: true },
            review: { disable_style_guard: 'yes' },
          },
        },
        buildtime_review_hooks: [], runtime_review_hooks: [],
      }),
    }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.llm_params).toEqual({
      director: { temperature: 0.8, disable_style_guard: true },
    })
  })

  it('model_ref 非空字符串原样透传', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => ({
        config: {
          llm_params: { director: { model_ref: 'custom-1' } },
          sandbox_llm_params: {},
        },
      }),
    })))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.llm_params.director).toEqual({ model_ref: 'custom-1' })
  })

  it('model_ref 为空字符串时丢弃', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => ({
        config: {
          llm_params: { director: { model_ref: '', temperature: 0.5 } },
          sandbox_llm_params: {},
        },
      }),
    })))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.llm_params.director).toEqual({ temperature: 0.5 })
  })

  it('import_llm_params 按 image_recognition/text_recognition 两个节点白名单解析', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => ({
        config: {
          llm_params: {}, sandbox_llm_params: {},
          import_llm_params: {
            image_recognition: { model_ref: 'custom-vision-1' },
            'not-a-real-node': { model_ref: 'x' },
          },
        },
      }),
    })))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.import_llm_params).toEqual({
      image_recognition: { model_ref: 'custom-vision-1' },
    })
  })

  it('fetchDialogueConfig 解析 chat_identity，缺省为空字符串', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: async () => ({}) }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.chat_identity).toBe('')
  })

  it('fetchDialogueConfig 解析 chat_identity 非空值原样透传', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({ config: { chat_identity: '自定义身份文案' } }),
    }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.chat_identity).toBe('自定义身份文案')
  })

  it('fetchDialogueConfig 解析 default_identity，缺省为空字符串', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: async () => ({}) }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.default_identity).toBe('')
  })

  it('fetchDialogueConfig 解析 default_identity 非空值原样透传', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({ default_identity: '内容包默认身份' }),
    }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.default_identity).toBe('内容包默认身份')
  })

  it('fetchDialogueConfig 解析 recall_cooldown_turns/recall_top_k', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: async () => ({
        config: { recall_cooldown_turns: 20, recall_top_k: 8 },
      }),
    }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.recall_cooldown_turns).toBe(20)
    expect(state.config.recall_top_k).toBe(8)
  })

  it('fetchDialogueConfig 缺字段时 recall_cooldown_turns/recall_top_k 降级为默认值', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: async () => ({}) }))
    const state = await fetchDialogueConfig('novel-1')
    expect(state.config.recall_cooldown_turns).toBe(10)
    expect(state.config.recall_top_k).toBe(5)
  })

  it('does not drop character_portrait.model_ref on round-trip', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: () => Promise.resolve({
        config: {
          import_llm_params: { character_portrait: { model_ref: 'img-1' } },
        },
      }),
    }))

    const result = await fetchDialogueConfig('novel-A')

    expect(result.config.import_llm_params.character_portrait?.model_ref).toBe('img-1')
  })
})
