import ModelRadioList from '@/shared/components/ModelRadioList'
import { Field } from '@/features/services/components/ServiceConfigPage'
import { Input } from '@/shared/components/ui/input'
import { useToast } from '@/shared/hooks/useToast'
import { useNovitaModelCatalog } from '@/features/services/queries/novitaModelCatalog'

export default function NovitaModelPicker({
  value, onChange,
}: { value: string; onChange: (model: string, baseModel: string | null) => void }) {
  const { success: toastSuccess, error: toastError } = useToast()
  const { data } = useNovitaModelCatalog()
  const models = data?.models ?? []
  const baseModels = data?.baseModels ?? {}

  const handleSearchMiss = () => {
    void fetch('/api/image-gen/novita-models/refresh', { method: 'POST' })
      .then(r => r.json())
      .then(body => {
        if (body.scheduled) toastSuccess('本地列表未命中，正在向 Novita 刷新目录…')
        else if (body.error) toastError(body.error)
      })
  }

  return (
    <>
      <ModelRadioList
        models={models}
        name="novita-model"
        selected={value}
        onSelect={(id) => onChange(id, baseModels[id] ?? null)}
        onSearchMiss={handleSearchMiss}
      />
      {models.length === 0 && (
        <Field label="模型 ID" hint="尚未拉取到 Novita 模型列表，可手动填入 sd_name。">
          <Input
            aria-label="模型 ID"
            className="w-full text-xs font-mono"
            value={value}
            onChange={e => onChange(e.target.value, null)}
          />
        </Field>
      )}
    </>
  )
}
