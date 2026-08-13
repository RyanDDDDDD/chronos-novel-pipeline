import type { ReactNode } from 'react'
import { Sidebar, SidebarContent, SidebarHeader } from '@/shared/components/ui/sidebar'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/shared/components/ui/tabs'

export const pipelinePanelSectionTitleClass = 'text-xs font-semibold text-[color:var(--c-text-secondary)]'
export const pipelinePanelHintClass = 'text-[11px] text-[color:var(--c-text-faint)]'

export const pipelinePanelCountInputClass =
  'w-16 px-1 py-0.5 text-sm font-medium tabular-nums text-[var(--c-accent)] ' +
  'bg-[var(--c-accent-subtle)] border border-[var(--c-tag-violet-border)] rounded-md text-center ' +
  'placeholder:text-[11px] placeholder:tracking-tight placeholder:text-[color:var(--c-text-faint)] ' +
  'focus:outline-none focus:ring-1 focus:ring-[var(--c-focus-ring)] focus:border-[var(--c-accent)] ' +
  'disabled:opacity-50'

export const pipelinePanelWideCountInputClass =
  'w-20 px-1 py-0.5 text-sm font-medium tabular-nums text-[var(--c-accent)] ' +
  'bg-[var(--c-accent-subtle)] border border-[var(--c-tag-violet-border)] rounded-md text-center ' +
  'placeholder:text-[11px] placeholder:tracking-tight placeholder:text-[color:var(--c-text-faint)] ' +
  'focus:outline-none focus:ring-1 focus:ring-[var(--c-focus-ring)] focus:border-[var(--c-accent)] ' +
  'disabled:opacity-50'

export function PipelineConfigSection({
  title, hint, children,
}: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div>
        <h3 className={pipelinePanelSectionTitleClass}>{title}</h3>
        {hint && <p className={`${pipelinePanelHintClass} mt-0.5`}>{hint}</p>}
      </div>
      {children}
    </section>
  )
}

export default function PipelineSidePanel({
  title, hint, children, skillContent,
}: { title: string; hint?: string; children: ReactNode; skillContent?: ReactNode }) {
  return (
    <Sidebar side="right" collapsible="offcanvas" className="shrink-0 border-[var(--c-border)]">
      <SidebarHeader className="px-3 py-2 border-b border-[var(--c-border-subtle)] shrink-0">
        <h2 className={pipelinePanelSectionTitleClass}>{title}</h2>
        {hint && <p className={`${pipelinePanelHintClass} mt-0.5`}>{hint}</p>}
      </SidebarHeader>
      {skillContent === undefined ? (
        <SidebarContent className="p-3 space-y-5">{children}</SidebarContent>
      ) : (
        <Tabs defaultValue="params" className="flex-1 min-h-0 flex flex-col">
          <TabsList className="mx-3 mt-2">
            <TabsTrigger value="params">参数</TabsTrigger>
            <TabsTrigger value="skill">Skill</TabsTrigger>
          </TabsList>
          <TabsContent value="params" className="flex-1 min-h-0 overflow-y-auto p-3 space-y-5">
            {children}
          </TabsContent>
          <TabsContent value="skill" className="flex-1 min-h-0 overflow-y-auto p-3 space-y-5">
            {skillContent}
          </TabsContent>
        </Tabs>
      )}
    </Sidebar>
  )
}
