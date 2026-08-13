import { useState } from 'react'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'

export interface StorySandboxBranchModalResult {
  name: string
  copyFromCurrent: boolean
}

interface Props {
  mode: 'create' | 'rename'
  /** Name of the currently active branch, if any. Drives whether the create-mode "copy from
   * current" radio is offered at all (no current branch => nothing to copy from). */
  currentBranchName?: string
  /** Pre-filled name -- current branch's name in rename mode, empty in create mode. */
  defaultName?: string
  onSubmit: (result: StorySandboxBranchModalResult) => void
  onClose: () => void
}

/** Replaces window.prompt for both "new story line" and "rename story line" -- see
 * TODO.md's 2026-08-03 StorySandbox 模态框重构条目. Create mode additionally offers an explicit
 * choice between branching off the current story line's content and starting from a blank one;
 * previously this always silently inherited the current branch (source_branch_id was passed
 * unconditionally whenever one was selected). */
export default function StorySandboxBranchModal({
  mode, currentBranchName, defaultName = '', onSubmit, onClose,
}: Props) {
  const [name, setName] = useState(defaultName)
  // Preserves the old implicit behavior as the default: a fresh branch, when one is currently
  // selected, used to always inherit it via source_branch_id.
  const [copyFromCurrent, setCopyFromCurrent] = useState(!!currentBranchName)

  const trimmed = name.trim()
  const canSubmit = mode === 'create' || trimmed.length > 0
  const submit = () => {
    if (!canSubmit) return
    onSubmit({ name: trimmed, copyFromCurrent })
  }

  return (
    <Dialog open onOpenChange={(next) => { if (!next) onClose() }}>
      <DialogContent className="max-w-sm p-0 overflow-hidden">
        <DialogHeader className="px-5 py-3.5 border-b border-[var(--c-border)]">
          <DialogTitle className="text-sm font-semibold">
            {mode === 'create' ? '新建故事线' : '重命名故事线'}
          </DialogTitle>
        </DialogHeader>
        <div className="px-5 py-4 flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-xs text-[var(--c-text-secondary)]">
            故事线名称
            <Input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={mode === 'create' ? '留空自动编号' : undefined}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  submit()
                }
              }}
            />
          </label>
          {mode === 'create' && currentBranchName && (
            <fieldset className="flex flex-col gap-1.5 text-xs text-[var(--c-text-secondary)]">
              <legend className="mb-0.5">新建方式</legend>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio" name="branch-create-mode" checked={copyFromCurrent}
                  onChange={() => setCopyFromCurrent(true)}
                />
                基于当前故事线「{currentBranchName}」复制
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio" name="branch-create-mode" checked={!copyFromCurrent}
                  onChange={() => setCopyFromCurrent(false)}
                />
                新建全新故事线（空白）
              </label>
            </fieldset>
          )}
        </div>
        <DialogFooter className="px-5 py-3 border-t border-[var(--c-border)]">
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="button" variant="default" onClick={submit} disabled={!canSubmit}>
            {mode === 'create' ? '新建' : '重命名'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
