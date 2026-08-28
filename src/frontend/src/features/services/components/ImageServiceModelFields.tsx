import { Field, ModelKeyRow } from '@/features/services/components/ServiceConfigPage'
import NovitaModelPicker from '@/features/services/components/NovitaModelPicker'
import {
  DEFAULT_NOVELAI_IMAGE_MODEL, NOVELAI_IMAGE_MODELS,
} from '@/features/services/utils/novelaiImageModels'
import { cn } from '@/shared/utils/cn'

type ImageService = 'novita' | 'novelai'

interface Draft {
  label: string
  model: string
  api_key: string
  base_model?: string | null
  service?: ImageService
}

const SERVICES: { id: ImageService; label: string }[] = [
  { id: 'novita', label: 'Novita' },
  { id: 'novelai', label: 'NovelAI' },
]

export default function ImageServiceModelFields<T extends Draft>({
  draft, onChange, showKey, onToggleKey,
}: {
  draft: T
  onChange: (next: T) => void
  showKey: boolean
  onToggleKey: () => void
}) {
  const service: ImageService = draft.service ?? 'novita'

  const setService = (next: ImageService) => {
    // Switching service invalidates the previously-picked model/base_model. NovelAI has a
    // fixed model list -- preselect the default so the entry is usable without a second click.
    onChange({
      ...draft, service: next, base_model: null,
      model: next === 'novelai' ? DEFAULT_NOVELAI_IMAGE_MODEL : '',
    })
  }

  return (
    <>
      <Field label="服务">
        <div className="flex gap-1">
          {SERVICES.map(s => (
            <button
              key={s.id}
              type="button"
              aria-pressed={service === s.id}
              onClick={() => setService(s.id)}
              className={cn(
                'px-2.5 py-1 text-xs rounded-md border',
                service === s.id
                  ? 'border-[var(--c-accent)] bg-[var(--c-accent-subtle)] text-[var(--c-accent)]'
                  : 'border-[var(--c-border)] text-[var(--c-text-secondary)]',
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
      </Field>

      <ModelKeyRow
        value={draft.api_key}
        revealed={showKey}
        onToggleReveal={onToggleKey}
        onChange={v => onChange({ ...draft, api_key: v })}
        showMissingWarning={false}
        label={service === 'novelai' ? 'NovelAI 持久 API Token' : undefined}
      />

      {service === 'novita' ? (
        <NovitaModelPicker
          value={draft.model}
          onChange={(v, baseModel) => onChange({
            ...draft, model: v, base_model: baseModel,
            label: draft.label === '' || draft.label === draft.model ? v : draft.label,
          })}
        />
      ) : (
        <Field label="模型" hint="NovelAI 账户设置 → Account → Get Persistent API Token（需有效订阅）">
          <select
            aria-label="NovelAI 模型"
            className="w-full text-xs rounded-md border border-[var(--c-border)] bg-[var(--c-surface)] px-2 py-1"
            value={draft.model}
            onChange={e => onChange({
              ...draft, model: e.target.value, base_model: null,
              label: draft.label === '' || draft.label === draft.model ? e.target.value : draft.label,
            })}
          >
            <option value="" disabled>选择模型</option>
            {NOVELAI_IMAGE_MODELS.map(m => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
          </select>
        </Field>
      )}
    </>
  )
}
