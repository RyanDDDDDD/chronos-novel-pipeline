import { useEffect, useMemo, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Eye, EyeOff } from 'lucide-react'
import { fetchModelCatalog, fetchLocalModels, fetchCompatibleModels, type CloudModelEntry } from '@/features/services/utils/llmCatalog'
import PageHeader from '@/shared/components/PageHeader'
import ModelRadioList from '@/shared/components/ModelRadioList'
import NovitaModelPicker from '@/features/services/components/NovitaModelPicker'
import CloudLoginDialog from '@/features/services/components/CloudLoginDialog'
import { loginStatusHydrated } from '@/features/services/store/cloudAuthSlice'
import { Switch } from '@/shared/components/ui/switch'
import { Input } from '@/shared/components/ui/input'
import { Textarea } from '@/shared/components/ui/textarea'
import { Button } from '@/shared/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import type { AppDispatch, RootState } from '@/shared/store/store'
import { fetchServiceStatus } from '@/shared/api/servicePing'
import {
  clampInt,
  fetchChronosConfig,
  saveChronosConfig,
  type ChronosConfig,
} from '@/shared/utils/chronosConfig'

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-slate-700">{label}</div>
      {children}
      {hint && <div className="text-[11px] text-slate-500">{hint}</div>}
    </div>
  )
}

const STYLE_GUARD_DEFAULT_VALUE = '__global_default__'

function Section({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <section className="border border-slate-200 rounded-lg bg-white p-4 space-y-3">
      <div>
        <div className="text-sm font-semibold text-slate-800">{title}</div>
        {desc && <div className="text-xs text-slate-500 mt-0.5">{desc}</div>}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {children}
      </div>
    </section>
  )
}

function ModelKeyRow({
  value, revealed, onToggleReveal, onChange, showMissingWarning,
}: {
  value: string
  revealed: boolean
  onToggleReveal: () => void
  onChange: (v: string) => void
  showMissingWarning: boolean
}) {
  return (
    <div className="pt-1.5 border-t border-slate-100 space-y-1">
      <div className="flex items-stretch gap-1">
        <Input
          className="flex-1 min-w-0 text-xs font-mono"
          type={revealed ? 'text' : 'password'}
          placeholder="API 密钥"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="shrink-0"
          onClick={onToggleReveal}
          title={revealed ? '隐藏' : '显示'}
          aria-label={revealed ? '隐藏' : '显示'}
        >
          {revealed ? <EyeOff size={14} /> : <Eye size={14} />}
        </Button>
      </div>
      {showMissingWarning && !value && (
        <div className="text-[11px] text-amber-700">当前选中模型未配置 key，调用会失败。</div>
      )}
    </div>
  )
}

interface CustomModelDraft {
  id: string
  label: string
  provider: 'anthropic' | 'openai_compatible' | 'image_gen'
  base_url: string
  model: string
  api_key: string
  base_model?: string | null
}

function CustomModelForm({
  draft, onChange, onSave, onCancel,
}: {
  draft: CustomModelDraft
  onChange: (next: CustomModelDraft) => void
  onSave: () => void
  onCancel: () => void
}) {
  const [revealed, setRevealed] = useState(false)
  const [fetchedModels, setFetchedModels] = useState<string[]>([])
  const [fetching, setFetching] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)
  // Existing label is treated as already-manual so switching model on an edited entry won't clobber it.
  const [labelTouched, setLabelTouched] = useState(() => draft.label.trim() !== '')

  const doFetch = () => {
    setFetching(true)
    void fetchCompatibleModels(draft.base_url, draft.api_key).then(({ models, error }) => {
      setFetchedModels(models)
      setFetchError(error ?? null)
      setFetching(false)
    })
  }

  const handleModelChange = (modelValue: string) => {
    onChange({
      ...draft,
      model: modelValue,
      label: labelTouched ? draft.label : modelValue,
    })
  }

  return (
    <div className="space-y-2 rounded-md border border-[var(--c-border)] bg-[var(--c-surface)] p-3">
      <Field label="模型显示名">
        <Input
          aria-label="模型显示名"
          className="w-full text-xs"
          value={draft.label}
          onChange={e => {
            setLabelTouched(true)
            onChange({ ...draft, label: e.target.value })
          }}
        />
      </Field>
      <Field label="提供商类型">
        <div className="flex gap-3">
          <label className="flex items-center gap-1.5 text-xs cursor-pointer">
            <input
              type="radio" name={`custom-provider-${draft.id}`}
              checked={draft.provider === 'openai_compatible'}
              onChange={() => onChange({ ...draft, provider: 'openai_compatible' })}
            />
            OpenAI 兼容
          </label>
          <label className="flex items-center gap-1.5 text-xs cursor-pointer">
            <input
              type="radio" name={`custom-provider-${draft.id}`}
              checked={draft.provider === 'anthropic'}
              onChange={() => onChange({ ...draft, provider: 'anthropic' })}
            />
            Anthropic
          </label>
        </div>
      </Field>
      <Field label="网关地址" hint="OpenAI 兼容网关根路径，如 https://api.example.com/v1（Anthropic 可留空）。对应 base_url。">
        <Input
          aria-label="网关地址"
          className="w-full text-xs font-mono"
          value={draft.base_url}
          onChange={e => onChange({ ...draft, base_url: e.target.value })}
        />
      </Field>
      <ModelKeyRow
        value={draft.api_key}
        revealed={revealed}
        onToggleReveal={() => setRevealed(v => !v)}
        onChange={v => onChange({ ...draft, api_key: v })}
        showMissingWarning={false}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="text-xs"
        onClick={doFetch}
        disabled={fetching}
      >
        {fetching ? '拉取中…' : '拉取模型列表'}
      </Button>
      {fetchError && (
        <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded p-2">{fetchError}</div>
      )}
      <ModelRadioList
        models={fetchedModels}
        name={`custom-model-${draft.id}`}
        selected={draft.model}
        onSelect={handleModelChange}
      />
      {fetchedModels.length === 0 && (
        <Field label="模型 ID" hint="未拉取到列表时，手动填入模型 id。对应 model。">
          <Input
            aria-label="模型 ID"
            className="w-full text-xs font-mono"
            value={draft.model}
            onChange={e => handleModelChange(e.target.value)}
          />
        </Field>
      )}
      <div className="flex gap-2">
        <Button
          type="button"
          variant="default"
          size="sm"
          className="text-xs"
          onClick={onSave}
        >
          保存此模型
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="text-xs"
          onClick={onCancel}
        >
          取消
        </Button>
      </div>
    </div>
  )
}

export default function ServiceConfigPage() {
  const dispatch = useDispatch<AppDispatch>()
  const isLoggedIn = useSelector((state: RootState) => state.cloudAuth.isLoggedIn)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cfg, setCfg] = useState<ChronosConfig>({})
  const [savedCfgText, setSavedCfgText] = useState('')
  const [showTavilyKey, setShowTavilyKey] = useState(false)
  const [showQianfanKey, setShowQianfanKey] = useState(false)
  const [loginDialogOpen, setLoginDialogOpen] = useState(false)
  const [revealedModelKeys, setRevealedModelKeys] = useState<Set<string>>(new Set())
  const toggleRevealed = (id: string) =>
    setRevealedModelKeys(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  const [showRaw, setShowRaw] = useState(false)
  const [rawText, setRawText] = useState('')
  const [modelTab, setModelTab] = useState<'cloud' | 'local'>('cloud')
  const [modelDomainTab, setModelDomainTab] = useState<'text' | 'image'>('text')
  const [imageModelTab, setImageModelTab] = useState<'cloud' | 'local'>('cloud')
  const [editingImageCustomModel, setEditingImageCustomModel] = useState<CustomModelDraft | null>(null)
  const [showImageKey, setShowImageKey] = useState(false)
  const [catalog, setCatalog] = useState<CloudModelEntry[]>([])
  const [localModels, setLocalModels] = useState<string[]>([])
  const [localModelsError, setLocalModelsError] = useState<string | null>(null)
  const [localModelsLoading, setLocalModelsLoading] = useState(false)
  const [editingCustomModel, setEditingCustomModel] = useState<CustomModelDraft | null>(null)

  useEffect(() => {
    void fetchModelCatalog().then(setCatalog)
  }, [])

  useEffect(() => {
    void fetch('/api/auth/status')
      .then(res => res.json())
      .then((body: { logged_in: boolean }) => dispatch(loginStatusHydrated(body.logged_in)))
      .catch(() => {})
  }, [dispatch])

  const refreshLocalModels = () => {
    setLocalModelsLoading(true)
    void fetchLocalModels(llmDraftLocalBaseUrl()).then(({ models, error }) => {
      setLocalModels(models)
      setLocalModelsError(error ?? null)
      setLocalModelsLoading(false)
    })
  }

  function llmDraftLocalBaseUrl(): string {
    return cfg.llm?.local_base_url ?? ''
  }

  useEffect(() => {
    if (modelTab === 'local') refreshLocalModels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelTab])

  useEffect(() => {
    let mounted = true
    setLoading(true)
    void (async () => {
      try {
        const c = await fetchChronosConfig()
        const text = JSON.stringify(c, null, 2)
        if (!mounted) return
        setCfg(c)
        setSavedCfgText(text)
        setRawText(text)
        setError(null)
      } catch (e) {
        if (!mounted) return
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (mounted) setLoading(false)
      }
    })()
    return () => { mounted = false }
  }, [])

  const currentText = useMemo(() => JSON.stringify(cfg, null, 2), [cfg])
  const dirty = useMemo(() => currentText.trim() !== savedCfgText.trim(), [currentText, savedCfgText])

  const patch = (fn: (c: ChronosConfig) => ChronosConfig) => setCfg((c) => fn(c))

  const onSave = async () => {
    setSaving(true)
    try {
      //If you are editing raw JSON, raw will take precedence (otherwise there will be a conflict between the form and raw)
      let next = cfg
      if (showRaw) {
        const parsed = JSON.parse(rawText) as unknown
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error('config 顶层必须是 JSON 对象（{ ... }）')
        }
        next = parsed as ChronosConfig
      }
      const merged = await saveChronosConfig(next)
      const text = JSON.stringify(merged, null, 2)
      setCfg(merged)
      setSavedCfgText(text)
      setRawText(text)
      setError(null)
      void fetchServiceStatus(dispatch)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const llm = cfg.llm ?? {}
  const api = cfg.api ?? {}
  const novels = cfg.novels ?? {}

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden bg-app">
      <PageHeader
        title="服务配置"
        subtitle={<>保存到 <code className="font-mono">config/config.json</code>（保存后会重载生效）。</>}
        actions={
          <Button
            type="button"
            variant="default"
            size="sm"
            className="text-xs"
            onClick={() => void onSave()}
            disabled={loading || saving || !dirty}
          >
            {saving ? '保存中…' : '保存'}
          </Button>
        }
      />

      <div className="shrink-0 px-4 py-2 border-b border-[var(--c-border)] bg-[var(--c-surface)] flex items-center gap-2">
        {dirty && !saving && <span className="text-xs text-amber-700">未保存修改</span>}
        {loading && <span className="text-xs text-[var(--c-text-muted)]">加载中…</span>}
        <div className="flex-1" />
        <label className="text-xs text-[var(--c-text-muted)] flex items-center gap-1.5 select-none">
          <Switch checked={showRaw} onCheckedChange={setShowRaw} />
          高级：原始 JSON
        </label>
      </div>

      <div className="flex-1 min-h-0 px-4 pt-3 pb-4 overflow-y-auto space-y-3">
        {error && (
          <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded p-2 whitespace-pre-wrap">
            {error}
          </div>
        )}

        <Section
          title="API 密钥"
          desc="设定共创 web_search 联网检索（Tavily / 百度千帆二选一）；仅本地推理时可留空。"
        >
          <Field label="检索提供商" hint="选择联网检索提供商，二选一生效。对应 api.search_provider。">
            <div className="flex gap-3">
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input
                  type="radio"
                  name="search_provider"
                  checked={(api.search_provider ?? 'tavily') === 'tavily'}
                  onChange={() => patch((c) => ({ ...c, api: { ...(c.api ?? {}), search_provider: 'tavily' } }))}
                />
                Tavily
              </label>
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input
                  type="radio"
                  name="search_provider"
                  checked={api.search_provider === 'baidu_qianfan'}
                  onChange={() => patch((c) => ({ ...c, api: { ...(c.api ?? {}), search_provider: 'baidu_qianfan' } }))}
                />
                百度千帆
              </label>
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input
                  type="radio"
                  name="search_provider"
                  checked={api.search_provider === 'chronos_cloud'}
                  onChange={() => patch((c) => ({ ...c, api: { ...(c.api ?? {}), search_provider: 'chronos_cloud' } }))}
                />
                Chronos 云端检索
              </label>
            </div>
          </Field>

          {api.search_provider === 'chronos_cloud' ? (
            <Field label="登录状态" hint="Chronos 云端检索需要登录账号，用量按登录用户计费/限流。">
              <div className="flex items-center gap-2">
                <span className="text-xs text-[var(--c-text-secondary)]">
                  {isLoggedIn ? '已登录' : '未登录'}
                </span>
                <Button type="button" variant="ghost" size="sm" onClick={() => setLoginDialogOpen(true)}>
                  {isLoggedIn ? '重新登录' : '登录'}
                </Button>
              </div>
            </Field>
          ) : (api.search_provider ?? 'tavily') === 'tavily' ? (
            <Field
              label="Tavily API Key"
              hint="设定共创 web_search 联网检索用；写入 api.tavily_api_key，保存后重载生效。"
            >
              <div className="flex items-stretch gap-1">
                <Input
                  className="flex-1 min-w-0 text-xs font-mono"
                  type={showTavilyKey ? 'text' : 'password'}
                  value={api.tavily_api_key ?? ''}
                  onChange={(e) => patch((c) => ({ ...c, api: { ...(c.api ?? {}), tavily_api_key: e.target.value } }))}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="shrink-0"
                  onClick={() => setShowTavilyKey(v => !v)}
                  title={showTavilyKey ? '隐藏' : '显示'}
                  aria-label={showTavilyKey ? '隐藏' : '显示'}
                >
                  {showTavilyKey ? <EyeOff size={14} /> : <Eye size={14} />}
                </Button>
              </div>
            </Field>
          ) : (
            <Field
              label="千帆 API Key"
              hint="设定共创 web_search 联网检索用（百度千帆 AppBuilder）；写入 api.qianfan_api_key，保存后重载生效。"
            >
              <div className="flex items-stretch gap-1">
                <Input
                  className="flex-1 min-w-0 text-xs font-mono"
                  type={showQianfanKey ? 'text' : 'password'}
                  value={api.qianfan_api_key ?? ''}
                  onChange={(e) => patch((c) => ({ ...c, api: { ...(c.api ?? {}), qianfan_api_key: e.target.value } }))}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="shrink-0"
                  onClick={() => setShowQianfanKey(v => !v)}
                  title={showQianfanKey ? '隐藏' : '显示'}
                  aria-label={showQianfanKey ? '隐藏' : '显示'}
                >
                  {showQianfanKey ? <EyeOff size={14} /> : <Eye size={14} />}
                </Button>
              </div>
            </Field>
          )}
          <CloudLoginDialog open={loginDialogOpen} onClose={() => setLoginDialogOpen(false)} />

          <Field label="检索条数上限" hint="单次联网检索返回条数上限（两路检索共用）。对应 api.search_top_k。">
            <Input
              type="text"
              inputMode="numeric"
              className="w-full text-xs font-mono"
              value={String(api.search_top_k ?? '')}
              onChange={(e) => patch((c) => ({
                ...c,
                api: { ...(c.api ?? {}), search_top_k: clampInt(e.target.value, 5) },
              }))}
            />
          </Field>
        </Section>

        <Section
          title="小说回收站"
          desc="删除的小说移入 data/novels/.trash/；超过保留天数后，在下次启动 backend 时自动物理清理。"
        >
          <Field
            label="回收站保留天数"
            hint="对应 novels.trash_retention_days；设为 0 关闭自动清理；保存后下次启动 backend 生效。"
          >
            <Input
              type="text"
              inputMode="numeric"
              className="w-full text-xs font-mono"
              value={String(novels.trash_retention_days ?? '')}
              onChange={(e) => patch((c) => ({
                ...c,
                novels: { ...(c.novels ?? {}), trash_retention_days: clampInt(e.target.value, 30) },
              }))}
            />
          </Field>
          <div className="hidden md:block" />
        </Section>

        <section className="border border-slate-200 rounded-lg bg-white p-4 space-y-3">
          <div>
            <div className="text-sm font-semibold text-slate-800">模型（LLM）</div>
            <div className="text-xs text-slate-500 mt-0.5">
              本地模型可实时读取推理服务当前加载的模型列表；自定义云端可拉取 OpenAI 兼容 /models 列表。
            </div>
          </div>
          <div className="flex gap-1 border-b border-slate-100 pb-2">
            <button
              type="button"
              className={`px-2.5 py-1 text-xs rounded-md ${modelDomainTab === 'text' ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)]' : 'text-slate-500 hover:bg-slate-50'}`}
              onClick={() => setModelDomainTab('text')}
            >
              文本模型
            </button>
            <button
              type="button"
              className={`px-2.5 py-1 text-xs rounded-md ${modelDomainTab === 'image' ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)]' : 'text-slate-500 hover:bg-slate-50'}`}
              onClick={() => setModelDomainTab('image')}
            >
              生图模型
            </button>
          </div>

          {modelDomainTab === 'text' && (
            <>
          <div className="flex gap-1 border-b border-slate-100 pb-2">
            <button
              type="button"
              className={`px-2.5 py-1 text-xs rounded-md ${modelTab === 'cloud' ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)]' : 'text-slate-500 hover:bg-slate-50'}`}
              onClick={() => setModelTab('cloud')}
            >
              云端模型
            </button>
            <button
              type="button"
              className={`px-2.5 py-1 text-xs rounded-md ${modelTab === 'local' ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)]' : 'text-slate-500 hover:bg-slate-50'}`}
              onClick={() => setModelTab('local')}
            >
              本地模型
            </button>
          </div>

          {modelTab === 'cloud' && (
            <div className="space-y-2">
              {catalog.map(entry => (
                <div
                  key={entry.id}
                  className={`border rounded-md px-3 py-2 text-xs ${
                    (llm.cloud_model_id ?? '') === entry.id ? 'border-[var(--c-accent)] bg-[var(--c-accent-subtle)]' : 'border-slate-200'
                  }`}
                >
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="cloud_model_id"
                      checked={(llm.cloud_model_id ?? '') === entry.id}
                      onChange={() => patch(c => ({ ...c, llm: { ...(c.llm ?? {}), cloud_model_id: entry.id } }))}
                    />
                    {entry.label}
                  </label>
                  <ModelKeyRow
                    value={api.model_api_keys?.[entry.id] ?? ''}
                    revealed={revealedModelKeys.has(entry.id)}
                    onToggleReveal={() => toggleRevealed(entry.id)}
                    onChange={(v) => patch(c => ({
                      ...c,
                      api: { ...(c.api ?? {}), model_api_keys: { ...(c.api?.model_api_keys ?? {}), [entry.id]: v } },
                    }))}
                    showMissingWarning={(llm.cloud_model_id ?? '') === entry.id}
                  />
                </div>
              ))}
              <div className="pt-2 space-y-2">
                <div className="text-xs font-semibold text-[var(--c-text-secondary)]">自定义模型</div>
                {(llm.custom_models ?? []).filter(m => m.provider !== 'image_gen').map(entry => (
                  <div
                    key={entry.id}
                    className={`border rounded-md px-3 py-2 text-xs space-y-1 ${
                      (llm.cloud_model_id ?? '') === entry.id ? 'border-[var(--c-accent)] bg-[var(--c-accent-subtle)]' : 'border-[var(--c-border)]'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <label className="flex items-center gap-2 cursor-pointer flex-1 min-w-0">
                        <input
                          type="radio"
                          name="cloud_model_id"
                          checked={(llm.cloud_model_id ?? '') === entry.id}
                          onChange={() => patch(c => ({ ...c, llm: { ...(c.llm ?? {}), cloud_model_id: entry.id } }))}
                        />
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="truncate">{entry.label || entry.model || entry.id}</span>
                          </TooltipTrigger>
                          <TooltipContent>{entry.label || entry.model || entry.id}</TooltipContent>
                        </Tooltip>
                      </label>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-auto px-2 py-0 text-xs text-[var(--c-text-muted)] hover:text-[var(--c-text-secondary)]"
                        onClick={() => setEditingCustomModel({
                          id: entry.id, label: entry.label, provider: entry.provider,
                          base_url: entry.base_url, model: entry.model, api_key: entry.api_key ?? '',
                        })}
                      >
                        编辑
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-auto px-2 py-0 text-xs text-rose-700 hover:text-rose-900"
                        onClick={() => patch(c => ({
                          ...c,
                          llm: { ...(c.llm ?? {}), custom_models: (c.llm?.custom_models ?? []).filter(m => m.id !== entry.id) },
                        }))}
                      >
                        删除
                      </Button>
                    </div>
                    {editingCustomModel?.id === entry.id && (
                      <CustomModelForm
                        draft={editingCustomModel}
                        onChange={setEditingCustomModel}
                        onCancel={() => setEditingCustomModel(null)}
                        onSave={() => {
                          patch(c => ({
                            ...c,
                            llm: {
                              ...(c.llm ?? {}),
                              custom_models: (c.llm?.custom_models ?? []).map(m => (
                                m.id === editingCustomModel.id
                                  ? { ...m, ...editingCustomModel, api_key: editingCustomModel.api_key }
                                  : m
                              )),
                            },
                          }))
                          setEditingCustomModel(null)
                        }}
                      />
                    )}
                  </div>
                ))}
                {editingCustomModel?.id === 'new' ? (
                  <CustomModelForm
                    draft={editingCustomModel}
                    onChange={setEditingCustomModel}
                    onCancel={() => setEditingCustomModel(null)}
                    onSave={() => {
                      patch(c => ({
                        ...c,
                        llm: {
                          ...(c.llm ?? {}),
                          custom_models: [...(c.llm?.custom_models ?? []), { ...editingCustomModel, id: crypto.randomUUID() }],
                        },
                      }))
                      setEditingCustomModel(null)
                    }}
                  />
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="text-xs"
                    onClick={() => setEditingCustomModel({
                      id: 'new', label: '', provider: 'openai_compatible',
                      base_url: '', model: '', api_key: '',
                    })}
                  >
                    添加模型
                  </Button>
                )}
              </div>
              <div className="pt-4 border-t border-[var(--c-border)] space-y-2">
                <div>
                  <div className="text-xs font-semibold text-[var(--c-text-secondary)]">文风守卫重写模型</div>
                  <div className="text-[11px] text-[var(--c-text-muted)] mt-0.5">
                    单句禁用词/句式局部重写专用；默认沿用上方全局默认且强制关闭思考模式。对应 llm.style_guard_model_ref。
                  </div>
                </div>
                <Select
                  value={(llm.style_guard_model_ref ?? '').trim() || STYLE_GUARD_DEFAULT_VALUE}
                  onValueChange={(v) => patch(c => ({
                    ...c,
                    llm: { ...(c.llm ?? {}), style_guard_model_ref: v === STYLE_GUARD_DEFAULT_VALUE ? '' : v },
                  }))}
                >
                  <SelectTrigger aria-label="文风守卫重写模型" className="w-full text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={STYLE_GUARD_DEFAULT_VALUE}>沿用全局默认（思考模式关闭）</SelectItem>
                    {[...catalog, ...(llm.custom_models ?? []).filter(m => m.provider !== 'image_gen')].map(entry => (
                      <SelectItem key={`style-guard-${entry.id}`} value={entry.id}>
                        {'label' in entry && entry.label ? entry.label : entry.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}

          {modelTab === 'local' && (
            <div className="space-y-2">
              <Field label="本地服务地址" hint={'默认：http://localhost:1234/v1（改动后点下方「重新连接」生效）。对应 llm.local_base_url。'}>
                <Input
                  aria-label="本地服务地址"
                  className="w-full text-xs font-mono"
                  value={llm.local_base_url ?? ''}
                  onChange={e => patch(c => ({ ...c, llm: { ...(c.llm ?? {}), local_base_url: e.target.value } }))}
                />
              </Field>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="text-xs"
                onClick={refreshLocalModels}
                disabled={localModelsLoading}
              >
                {localModelsLoading ? '连接中…' : '重新连接'}
              </Button>
              {localModelsError && (
                <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded p-2">
                  {localModelsError}
                </div>
              )}
              <ModelRadioList
                models={localModels}
                name="local_model"
                selected={llm.local_model}
                onSelect={id => patch(c => ({ ...c, llm: { ...(c.llm ?? {}), local_model: id } }))}
              />
              {localModels.length === 0 && (
                <Field label="本地模型" hint="未连接到本地推理服务时，手动填入模型名。对应 llm.local_model。">
                  <Input
                    aria-label="本地模型"
                    className="w-full text-xs font-mono"
                    value={llm.local_model ?? ''}
                    onChange={e => patch(c => ({ ...c, llm: { ...(c.llm ?? {}), local_model: e.target.value } }))}
                  />
                </Field>
              )}
              <Field label="最大 Token 数" hint="单次调用最大 token 上限。对应 llm.max_tokens。">
                <Input
                  type="text"
                  inputMode="numeric"
                  className="w-full text-xs font-mono"
                  value={String(llm.max_tokens ?? '')}
                  onChange={e => patch(c => ({
                    ...c,
                    llm: { ...(c.llm ?? {}), max_tokens: clampInt(e.target.value, 8000) },
                  }))}
                />
              </Field>
              <Field label="本地参数预设" hint="读取 config/local_model_presets.json 的 presets.<name> 合并进 llm 参数。对应 llm.local_preset。">
                <Input
                  aria-label="本地参数预设"
                  className="w-full text-xs font-mono"
                  value={llm.local_preset ?? ''}
                  onChange={e => patch(c => ({ ...c, llm: { ...(c.llm ?? {}), local_preset: e.target.value } }))}
                />
              </Field>
            </div>
          )}
            </>
          )}

          {modelDomainTab === 'image' && (
            <div className="space-y-2">
              <div className="flex gap-1 border-b border-slate-100 pb-2">
                <button
                  type="button"
                  className={`px-2.5 py-1 text-xs rounded-md ${imageModelTab === 'cloud' ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)]' : 'text-slate-500 hover:bg-slate-50'}`}
                  onClick={() => setImageModelTab('cloud')}
                >
                  云端
                </button>
                <button
                  type="button"
                  className={`px-2.5 py-1 text-xs rounded-md ${imageModelTab === 'local' ? 'bg-[var(--c-accent-subtle)] text-[var(--c-accent)]' : 'text-slate-500 hover:bg-slate-50'}`}
                  onClick={() => setImageModelTab('local')}
                >
                  本地
                </button>
              </div>

              {imageModelTab === 'cloud' && (
                <div className="space-y-2">
                  {(llm.custom_models ?? []).filter(m => m.provider === 'image_gen').map(entry => (
                    <div key={entry.id} className="border rounded-md px-3 py-2 text-xs space-y-1 border-[var(--c-border)]">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate">{entry.label || entry.model || entry.id}</span>
                        <Button
                          type="button" variant="ghost" size="sm"
                          className="h-auto px-2 py-0 text-xs text-[var(--c-text-muted)] hover:text-[var(--c-text-secondary)]"
                          onClick={() => setEditingImageCustomModel({
                            id: entry.id, label: entry.label, provider: 'image_gen',
                            base_url: entry.base_url, model: entry.model, api_key: entry.api_key ?? '',
                          })}
                        >
                          编辑
                        </Button>
                        <Button
                          type="button" variant="ghost" size="sm"
                          className="h-auto px-2 py-0 text-xs text-rose-700 hover:text-rose-900"
                          onClick={() => patch(c => ({
                            ...c,
                            llm: { ...(c.llm ?? {}), custom_models: (c.llm?.custom_models ?? []).filter(m => m.id !== entry.id) },
                          }))}
                        >
                          删除
                        </Button>
                      </div>
                      {editingImageCustomModel?.id === entry.id && (
                        <div className="space-y-2 rounded-md border border-[var(--c-border)] bg-[var(--c-surface)] p-3">
                          <Field label="显示名">
                            <Input
                              aria-label="显示名"
                              className="w-full text-xs"
                              value={editingImageCustomModel.label}
                              onChange={e => setEditingImageCustomModel({ ...editingImageCustomModel, label: e.target.value })}
                            />
                          </Field>
                          <ModelKeyRow
                            value={editingImageCustomModel.api_key}
                            revealed={showImageKey}
                            onToggleReveal={() => setShowImageKey(v => !v)}
                            onChange={v => setEditingImageCustomModel({ ...editingImageCustomModel, api_key: v })}
                            showMissingWarning={false}
                          />
                          <NovitaModelPicker
                            value={editingImageCustomModel.model}
                            onChange={(v, baseModel) => setEditingImageCustomModel(prev => (prev && ({
                              ...prev, model: v, base_model: baseModel,
                              label: (prev.label === '' || prev.label === prev.model) ? v : prev.label,
                            })))}
                          />
                          <div className="flex gap-2">
                            <Button
                              type="button" variant="default" size="sm" className="text-xs"
                              onClick={() => {
                                patch(c => ({
                                  ...c,
                                  llm: {
                                    ...(c.llm ?? {}),
                                    custom_models: (c.llm?.custom_models ?? []).map(m => (
                                      m.id === editingImageCustomModel.id ? { ...m, ...editingImageCustomModel } : m
                                    )),
                                  },
                                }))
                                setEditingImageCustomModel(null)
                              }}
                            >
                              保存此模型
                            </Button>
                            <Button
                              type="button" variant="outline" size="sm" className="text-xs"
                              onClick={() => setEditingImageCustomModel(null)}
                            >
                              取消
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                  {editingImageCustomModel?.id === 'new' ? (
                    <div className="space-y-2 rounded-md border border-[var(--c-border)] bg-[var(--c-surface)] p-3">
                      <Field label="显示名">
                        <Input
                          aria-label="显示名"
                          className="w-full text-xs"
                          value={editingImageCustomModel.label}
                          onChange={e => setEditingImageCustomModel({ ...editingImageCustomModel, label: e.target.value })}
                        />
                      </Field>
                      <ModelKeyRow
                        value={editingImageCustomModel.api_key}
                        revealed={showImageKey}
                        onToggleReveal={() => setShowImageKey(v => !v)}
                        onChange={v => setEditingImageCustomModel({ ...editingImageCustomModel, api_key: v })}
                        showMissingWarning={false}
                      />
                      <NovitaModelPicker
                        value={editingImageCustomModel.model}
                        onChange={(v, baseModel) => setEditingImageCustomModel(prev => (prev && ({
                          ...prev, model: v, base_model: baseModel,
                          label: (prev.label === '' || prev.label === prev.model) ? v : prev.label,
                        })))}
                      />
                      <div className="flex gap-2">
                        <Button
                          type="button" variant="default" size="sm" className="text-xs"
                          onClick={() => {
                            patch(c => ({
                              ...c,
                              llm: {
                                ...(c.llm ?? {}),
                                custom_models: [...(c.llm?.custom_models ?? []), { ...editingImageCustomModel, id: crypto.randomUUID() }],
                              },
                            }))
                            setEditingImageCustomModel(null)
                          }}
                        >
                          保存此模型
                        </Button>
                        <Button
                          type="button" variant="outline" size="sm" className="text-xs"
                          onClick={() => setEditingImageCustomModel(null)}
                        >
                          取消
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <Button
                      type="button" variant="outline" size="sm" className="text-xs"
                      onClick={() => setEditingImageCustomModel({
                        id: 'new', label: '', provider: 'image_gen', base_url: '', model: '', api_key: '',
                      })}
                    >
                      添加生图模型
                    </Button>
                  )}
                </div>
              )}

              {imageModelTab === 'local' && (
                <div className="rounded-md border border-dashed border-[var(--c-border)] p-4 text-center text-xs text-[var(--c-text-muted)]">
                  暂不支持本地生图模型
                </div>
              )}
            </div>
          )}
        </section>

        {showRaw && (
          <section className="border border-slate-200 rounded-lg bg-white p-4 space-y-2">
            <div className="flex items-center gap-2">
              <div className="text-sm font-semibold text-slate-800">高级：原始 JSON</div>
              <div className="flex-1" />
              <Button
                type="button"
                variant="link"
                className="h-auto p-0 text-xs text-[color:var(--c-text-secondary)] hover:text-[color:var(--c-text)]"
                onClick={() => setRawText(currentText)}
                title="从当前表单状态刷新到 JSON"
              >
                从表单刷新
              </Button>
            </div>
            <Textarea
              className="w-full min-h-[16rem] font-mono text-xs bg-slate-50"
              value={rawText}
              onChange={(e) => setRawText(e.target.value)}
              spellCheck={false}
            />
            <div className="text-[11px] text-slate-500">
              提示：当你在此处编辑时，保存将以此 JSON 为准（覆盖上方表单的改动）。
            </div>
          </section>
        )}
      </div>
    </div>
  )
}

