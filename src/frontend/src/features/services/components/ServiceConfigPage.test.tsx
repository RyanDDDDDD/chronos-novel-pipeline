import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Provider } from 'react-redux'
import { buildTestStore } from '@/test/renderWithClient'
import { TooltipProvider } from '@/shared/components/ui/tooltip'
import ServiceConfigPage from '@/features/services/components/ServiceConfigPage'

function renderPage() {
  const store = buildTestStore()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  return render(
    <TooltipProvider>
      <Provider store={store}>
        <QueryClientProvider client={client}>
          <ServiceConfigPage />
        </QueryClientProvider>
      </Provider>
    </TooltipProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/api/config') {
      return { ok: true, json: async () => ({ config: { llm: { cloud_model_id: 'claude-opus-4-7', custom_models: [], local_base_url: 'http://localhost:1234/v1' } } }) }
    }
    if (url === '/api/llm/catalog') {
      return { ok: true, json: async () => ({ cloud_models: [{ id: 'claude-opus-4-7', label: 'Claude Opus 4.7', provider: 'anthropic' }] }) }
    }
    return { ok: true, json: async () => ({ models: [] }) }
  }))
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ServiceConfigPage model tabs', () => {
  it('默认渲染云端 tab，展示目录模型名称', async () => {
    renderPage()
    await waitFor(() => expect(screen.getAllByText('Claude Opus 4.7').length).toBeGreaterThan(0))
    expect(screen.queryByText(/每百万 token/)).toBeNull()
  })

  it('切到本地 tab 后不显示云端目录列表', async () => {
    renderPage()
    await waitFor(() => expect(screen.getAllByText('Claude Opus 4.7').length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: '本地模型' }))
    await waitFor(() => expect(screen.queryByText('Claude Opus 4.7')).toBeNull())
  })

  it('本地模型连接失败时显示错误与 manual local_model 输入', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/config') {
        return { ok: true, json: async () => ({ config: { llm: { local_base_url: 'http://localhost:1234/v1' } } }) }
      }
      if (url === '/api/llm/catalog') {
        return { ok: true, json: async () => ({ cloud_models: [] }) }
      }
      if (url.startsWith('/api/llm/local-models')) {
        return { ok: true, json: async () => ({ models: [], error: '连接被拒绝' }) }
      }
      return { ok: true, json: async () => ({}) }
    }))

    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: '本地模型' })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '本地模型' }))

    await waitFor(() => expect(screen.getByText('连接被拒绝')).toBeTruthy())
    expect(screen.getByLabelText('本地模型')).toBeTruthy()
  })

  it('编辑自定义模型时拉取模型列表后展示可选 radio', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/config') {
        return {
          ok: true,
          json: async () => ({
            config: {
              llm: {
                cloud_model_id: 'custom',
                custom_models: [{
                  id: 'custom', label: '自定义（迁移）', provider: 'openai_compatible',
                  base_url: 'https://proxy.example/v1', model: '', api_key: 'sk-test', client_kwargs: {},
                }],
              },
            },
          }),
        }
      }
      if (url === '/api/llm/catalog') {
        return { ok: true, json: async () => ({ cloud_models: [] }) }
      }
      if (url === '/api/llm/compatible-models' && init?.method === 'POST') {
        return { ok: true, json: async () => ({ models: ['fetched-model-a'] }) }
      }
      return { ok: true, json: async () => ({}) }
    }))

    renderPage()
    await waitFor(() => expect(screen.getAllByText('自定义（迁移）').length).toBeGreaterThan(0))
    fireEvent.click(screen.getAllByRole('button', { name: '编辑' })[0])
    await waitFor(() => expect(screen.getByRole('button', { name: '拉取模型列表' })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '拉取模型列表' }))
    await waitFor(() => expect(screen.getByText('fetched-model-a')).toBeTruthy())
  })

  it('模型列表支持搜索过滤', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/config') {
        return {
          ok: true,
          json: async () => ({
            config: {
              llm: {
                cloud_model_id: 'custom',
                custom_models: [{
                  id: 'custom', label: '自定义（迁移）', provider: 'openai_compatible',
                  base_url: 'https://proxy.example/v1', model: '', api_key: 'sk-test', client_kwargs: {},
                }],
              },
            },
          }),
        }
      }
      if (url === '/api/llm/catalog') {
        return { ok: true, json: async () => ({ cloud_models: [] }) }
      }
      if (url === '/api/llm/compatible-models' && init?.method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            models: ['anthropic/claude-3.5-sonnet', 'google/gemini-2.5-flash', 'deepseek/deepseek-chat'],
          }),
        }
      }
      return { ok: true, json: async () => ({}) }
    }))

    renderPage()
    await waitFor(() => expect(screen.getAllByText('自定义（迁移）').length).toBeGreaterThan(0))
    fireEvent.click(screen.getAllByRole('button', { name: '编辑' })[0])
    await waitFor(() => expect(screen.getByRole('button', { name: '拉取模型列表' })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '拉取模型列表' }))
    await waitFor(() => expect(screen.getByText('anthropic/claude-3.5-sonnet')).toBeTruthy())

    fireEvent.change(screen.getByRole('searchbox', { name: '搜索模型' }), { target: { value: 'gemini' } })
    await waitFor(() => expect(screen.getByText('google/gemini-2.5-flash')).toBeTruthy())
    expect(screen.queryByText('anthropic/claude-3.5-sonnet')).toBeNull()
    expect(screen.getByText('显示 1 / 3 个模型')).toBeTruthy()
  })

  it('切到「生图模型」tab 显示云端自定义生图条目管理', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/config') {
        return {
          ok: true,
          json: async () => ({
            config: {
              llm: {
                custom_models: [{
                  id: 'img-1', label: '我的Novita', provider: 'image_gen',
                  base_url: '', model: 'flux-1', api_key: 'sk-test',
                }],
              },
            },
          }),
        }
      }
      if (url === '/api/llm/catalog') {
        return { ok: true, json: async () => ({ cloud_models: [] }) }
      }
      return { ok: true, json: async () => ({}) }
    }))

    renderPage()
    fireEvent.click(await screen.findByText('生图模型'))
    expect(await screen.findByText('我的Novita')).not.toBeNull()
  })

  it('「生图模型」tab 下「本地」子 tab 只显示占位文案，不发请求', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/config') {
        return { ok: true, json: async () => ({ config: { llm: { custom_models: [] } } }) }
      }
      if (url === '/api/llm/catalog') {
        return { ok: true, json: async () => ({ cloud_models: [] }) }
      }
      return { ok: true, json: async () => ({}) }
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    fireEvent.click(await screen.findByText('生图模型'))
    fireEvent.click(await screen.findByText('本地'))
    expect(await screen.findByText('暂不支持本地生图模型')).not.toBeNull()
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('local-models'))).toBe(false)
  })

  it('文本模型 tab 的自定义模型列表不显示 image_gen 类条目', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/config') {
        return {
          ok: true,
          json: async () => ({
            config: {
              llm: {
                cloud_model_id: 'text-1',
                custom_models: [
                  { id: 'text-1', label: '文本模型A', provider: 'openai_compatible', base_url: 'https://x/v1', model: 'm1', api_key: '' },
                  { id: 'img-1', label: '生图模型B', provider: 'image_gen', base_url: '', model: 'flux-1', api_key: '' },
                ],
              },
            },
          }),
        }
      }
      if (url === '/api/llm/catalog') {
        return { ok: true, json: async () => ({ cloud_models: [] }) }
      }
      return { ok: true, json: async () => ({}) }
    }))

    renderPage()
    await waitFor(() => expect(screen.getAllByText('文本模型A').length).toBeGreaterThan(0))
    expect(screen.queryByText('生图模型B')).toBeNull()
  })
})

describe('ServiceConfigPage 自定义模型表格', () => {
  it('添加一条自定义模型后出现在列表与 radio 组里', async () => {
    let savedConfig: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/config' && (!init || init.method === undefined)) {
        return { ok: true, json: async () => ({ config: { llm: { cloud_model_id: 'claude-opus-4-7', custom_models: [] } } }) }
      }
      if (url === '/api/config' && init?.method === 'PUT') {
        savedConfig = JSON.parse(String(init.body))
        return { ok: true, json: async () => savedConfig }
      }
      if (url === '/api/llm/catalog') {
        return { ok: true, json: async () => ({ cloud_models: [] }) }
      }
      return { ok: true, json: async () => ({}) }
    }))

    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: '添加模型' })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '添加模型' }))
    fireEvent.change(screen.getByLabelText('模型显示名'), { target: { value: '我的新模型' } })
    fireEvent.change(screen.getByLabelText('网关地址'), { target: { value: 'https://new.example.com/v1' } })
    fireEvent.change(screen.getByLabelText('模型 ID'), { target: { value: 'new-model-id' } })
    fireEvent.click(screen.getByRole('button', { name: '保存此模型' }))
    await waitFor(() => expect(screen.getAllByText('我的新模型').length).toBeGreaterThan(0))

    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(savedConfig).not.toBeNull())
    const cfg = savedConfig as { config: { llm: { custom_models: { label: string; base_url: string; model: string }[] } } }
    expect(cfg.config.llm.custom_models).toHaveLength(1)
    expect(cfg.config.llm.custom_models[0]).toMatchObject({
      label: '我的新模型', base_url: 'https://new.example.com/v1', model: 'new-model-id',
    })
  })

  it('选中 Novita checkpoint 时把 base_model 一并存进新建的生图模型草稿', async () => {
    let savedConfig: { config: { llm: { custom_models: { model: string; base_model?: string }[] } } } | null = null
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/config' && (!init || init.method === undefined)) {
        return { ok: true, json: async () => ({ config: { llm: { custom_models: [] } } }) }
      }
      if (url === '/api/config' && init?.method === 'PUT') {
        savedConfig = JSON.parse(String(init.body))
        return { ok: true, json: async () => savedConfig }
      }
      if (url === '/api/llm/catalog') {
        return { ok: true, json: async () => ({ cloud_models: [] }) }
      }
      if (url === '/api/image-gen/novita-models') {
        return {
          ok: true,
          json: async () => ({
            models: ['pony-v6.safetensors'],
            base_models: { 'pony-v6.safetensors': 'Pony' },
          }),
        }
      }
      return { ok: true, json: async () => ({}) }
    }))

    renderPage()
    fireEvent.click(await screen.findByText('生图模型'))
    fireEvent.click(await screen.findByRole('button', { name: '添加生图模型' }))
    fireEvent.click(await screen.findByText('pony-v6.safetensors'))
    fireEvent.click(screen.getByRole('button', { name: '保存此模型' }))

    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(savedConfig).not.toBeNull())

    const entry = savedConfig!.config.llm.custom_models.find(m => m.model === 'pony-v6.safetensors')
    expect(entry.base_model).toBe('Pony')
  })

  it('删除一条自定义模型后从列表消失', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/config') {
        return {
          ok: true,
          json: async () => ({
            config: {
              llm: {
                cloud_model_id: 'to-delete',
                custom_models: [{
                  id: 'to-delete', label: '待删除', provider: 'openai_compatible',
                  base_url: 'https://x.example.com/v1', model: 'm', api_key: '', client_kwargs: {},
                }],
              },
            },
          }),
        }
      }
      if (url === '/api/llm/catalog') {
        return { ok: true, json: async () => ({ cloud_models: [] }) }
      }
      return { ok: true, json: async () => ({}) }
    }))

    renderPage()
    await waitFor(() => expect(screen.getAllByText('待删除').length).toBeGreaterThan(0))
    fireEvent.click(screen.getAllByRole('button', { name: '删除' })[0])
    await waitFor(() => expect(screen.queryByText('待删除')).toBeNull())
  })
})

describe('联网检索 provider 切换', () => {
  it('默认显示 Tavily key 字段；切到百度千帆后显示对应 key 字段', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Tavily API Key')).toBeTruthy())
    expect(screen.queryByText('千帆 API Key')).toBeNull()

    fireEvent.click(screen.getByText('百度千帆'))

    await waitFor(() => expect(screen.getByText('千帆 API Key')).toBeTruthy())
    expect(screen.queryByText('Tavily API Key')).toBeNull()
  })

  it('渲染 search_top_k 字段', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/config') {
        return { ok: true, json: async () => ({ config: { api: { search_top_k: 8 } } }) }
      }
      if (url === '/api/llm/catalog') {
        return { ok: true, json: async () => ({ cloud_models: [] }) }
      }
      return { ok: true, json: async () => ({ models: [] }) }
    }))
    renderPage()
    await waitFor(() => expect(screen.getByText('检索条数上限')).toBeTruthy())
    expect(screen.getByDisplayValue('8')).toBeTruthy()
  })
})

describe('search_ping_enabled + 保存后触发连通性检测', () => {
  it('渲染 search_ping_enabled switch，默认未勾选', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('启动时检测检索连通性')).toBeTruthy())
    const pingSwitch = screen.getByRole('switch', { name: '应用启动时自动检测检索服务连通性' })
    expect(pingSwitch.getAttribute('aria-checked')).toBe('false')
  })

  it('保存成功后拉取 service-status（连通性检测由后端 PUT /api/config 触发）', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url}`)
      if (url === '/api/config' && init?.method === undefined) {
        return {
          ok: true,
          json: async () => ({
            config: { llm: { cloud_model_id: 'claude-opus-4-7', custom_cloud: {} }, api: { tavily_api_key: 'k' } },
          }),
        }
      }
      if (url === '/api/config' && init?.method === 'PUT') {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            config: { llm: { cloud_model_id: 'claude-opus-4-7', custom_cloud: {} }, api: { tavily_api_key: 'k2' } },
          }),
        }
      }
      if (url === '/api/llm/catalog') {
        return { ok: true, json: async () => ({ cloud_models: [] }) }
      }
      if (url === '/api/health/service-status') {
        return {
          ok: true,
          json: async () => ({
            llm: { status: 'ok', error: null },
            search: { status: 'ok', error: null },
          }),
        }
      }
      return { ok: true, json: async () => ({ models: [] }) }
    }))

    renderPage()
    await waitFor(() => expect(screen.getByDisplayValue('k')).toBeTruthy())
    fireEvent.change(screen.getByDisplayValue('k'), { target: { value: 'k2' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(calls).toContain('PUT /api/config'))
    await waitFor(() => expect(calls).toContain('GET /api/health/service-status'))
    expect(calls.some(c => c.includes('ping-llm'))).toBe(false)
    expect(calls.some(c => c.includes('ping-search'))).toBe(false)
  })
})
