import StageHandles from '@/features/pipeline/components/StageHandles'

interface Data {
  label: string
  hint?: string
  selected?: boolean
}

export default function DialogueDirectorNode({ data }: { data: Data }) {
  const selectedStyle = data.selected ? ' ring-2 ring-[var(--c-accent)] ring-offset-1' : ''
  return (
    <div className={`rounded-lg border-2 border-[var(--c-tag-violet-border)] bg-white min-w-[12rem]${selectedStyle}`}>
      <StageHandles />
      <div className="px-3 pt-2.5 pb-2 text-xs text-slate-700">
        <div className="font-semibold">{data.label}</div>
        <div className="text-[10px] text-slate-400 mt-1">{data.hint ?? '点击节点配置采样参数'}</div>
      </div>
    </div>
  )
}
