import { useParams } from 'react-router-dom'
import SetupChatPanel from '@/features/chat/components/SetupChatPanel'
import PageHeader from '@/shared/components/PageHeader'

/** Settings co-creation dialog: independent view separate from world/cast/plot settings page. */
export default function SetupChatPage() {
  const novelId = useParams().novelId ?? ''
  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden bg-app">
      <PageHeader title="对话精修" subtitle="与设定共创者对话，增量修改世界观、人物与剧情。" />
      <div className="flex-1 min-h-0 min-w-0 flex">
        <div className="flex-1 min-h-0 min-w-0 flex flex-col px-4 pt-4 pb-4">
          {novelId ? (
            <SetupChatPanel novelId={novelId} cacheKey={`setup-chat:${novelId}`} />
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm text-slate-400">加载中…</div>
          )}
        </div>
      </div>
    </div>
  )
}
