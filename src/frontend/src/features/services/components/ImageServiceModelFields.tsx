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

const novelaiLabel = (id: string) => NOVELAI_IMAGE_MODELS.find(m => m.id === id)?.label ?? id

export default function ImageServiceModelFields<T extends Draft>({
  draft, onChange, showKey, onToggleKey,
}: {
  draft: T
  onChange: (next: T) => void
  showKey: boolean
  onToggleKey: () => void
}) {
  const service: ImageService = draft.service ?? 'novita'

  // The display name auto-syncs to the model as long as the user hasn't hand-typed one.
  // "not hand-typed" == blank, or still equal to the current model's raw id / friendly label.
  const labelIsAuto = draft.label === '' || draft.label === draft.model
    || draft.label === novelaiLabel(draft.model)

  const pickModel = (next: Partial<T>) => onChange({
    ...draft, ...next, base_model: null,
    label: labelIsAuto ? novelaiLabel(String(next.model ?? draft.model)) : draft.label,
  } as T)

  const setService = (next: ImageService) => {
    if (next === service) return // clicking the already-active service must not clear the picked model
    // Switching service invalidates the previously-picked model/base_model. NovelAI has a
    // fixed model list -- preselect the default (and its label, since the pre-selected
    // <option> never fires onChange) so the entry is usable and named without extra clicks.
    if (next === 'novelai') {
      pickModel({ service: next, model: DEFAULT_NOVELAI_IMAGE_MODEL } as Partial<T>)
    } else {
      onChange({ ...draft, service: next, base_model: null, model: '' } as T)
    }
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
            label: labelIsAuto ? v : draft.label,
          } as T)}
        />
      ) : (
        <Field label="模型" hint="NovelAI 账户设置 → Account → Get Persistent API Token（需有效订阅）">
          <select
            aria-label="NovelAI 模型"
            className="w-full text-xs rounded-md border border-[var(--c-border)] bg-[var(--c-surface)] px-2 py-1"
            value={draft.model}
            onChange={e => pickModel({ model: e.target.value } as Partial<T>)}
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
