import StageHandles from '@/features/pipeline/components/StageHandles'

interface Data {
  label: string
  /** 异步/不阻塞主链路节点（如 post-beat 自审/守卫），虚线边框区分于同步主链路节点。 */
  async?: boolean
  /** 当前是否被点击选中（驱动采样参数悬浮面板的展示内容）。 */
  selected?: boolean
}

export default function MechanismStageNode({ data }: { data: Data }) {
  const asyncStyle = data.async
    ? 'border border-dashed border-slate-300 bg-slate-50/60'
    : 'border border-slate-200 bg-slate-50'
  const selectedStyle = data.selected ? ' ring-2 ring-[var(--c-accent)] ring-offset-1' : ''
  return (
    <div className={`rounded-lg min-w-[9rem] ${asyncStyle}${selectedStyle}`}>
      <StageHandles />
      <div className="px-3 pt-2.5 pb-2 text-xs text-slate-400">
        <div className="font-medium text-slate-600">{data.label}</div>
        <div className="text-[10px] mt-0.5">{data.async ? '异步机制（不阻塞主链路）' : '固定机制'}</div>
      </div>
    </div>
  )
}
