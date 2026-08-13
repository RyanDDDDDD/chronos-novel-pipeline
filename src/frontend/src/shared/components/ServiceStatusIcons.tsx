import { useSelector } from 'react-redux'
import { selectServicePing, type PingEntry, type PingStatus } from '@/shared/store/servicePingSlice'

const STATUS_DOT_CLASS: Record<PingStatus, string> = {
  ok: 'bg-emerald-500',
  error: 'bg-red-500',
  checking: 'bg-amber-400 animate-pulse',
  unknown: 'bg-slate-300',
  disabled: 'bg-slate-300 opacity-60',
}

function statusTitle(label: string, entry: PingEntry): string {
  switch (entry.status) {
    case 'ok':
      return `${label}已连接`
    case 'error':
      return `${label}连接失败${entry.error ? `：${entry.error}` : ''}`
    case 'checking':
      return `正在检测${label}…`
    case 'disabled':
      return `启动自动检测已关闭（保存设置后仍会检测${label}）`
    default:
      return `${label}尚未检测`
  }
}

function StatusDot({ label, entry }: { label: string; entry: PingEntry }) {
  return (
    <span
      title={statusTitle(label, entry)}
      className={`inline-block size-2 rounded-full shrink-0 ${STATUS_DOT_CLASS[entry.status]}`}
    />
  )
}

/** Connectivity indicators for the currently configured cloud LLM and search
 * provider -- status is owned by the backend (startup ping + config-save ping);
 * the frontend only reads GET /api/health/service-status. Rendered in NovelRail. */
export default function ServiceStatusIcons({ collapsed }: { collapsed: boolean }) {
  const { llm, search } = useSelector(selectServicePing)

  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-1 py-1">
        <StatusDot label="LLM" entry={llm} />
        <StatusDot label="检索" entry={search} />
      </div>
    )
  }

  return (
    <div className="flex items-center gap-3 px-2.5 py-1.5 text-[11px] text-[color:var(--c-text-muted)]">
      <span className="flex items-center gap-1.5">
        <StatusDot label="LLM" entry={llm} />
        LLM
      </span>
      <span className="flex items-center gap-1.5">
        <StatusDot label="检索" entry={search} />
        检索
      </span>
    </div>
  )
}
