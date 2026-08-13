import { ChevronDownIcon, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'

type StorySandboxBranchMenuProps = {
  branchId: string | null
  busy: boolean
  isSyncing: boolean
  onCreate: () => void
  onRename: () => void
  onReset: () => void
  onDelete: () => void
}

/** Branch lifecycle actions (create / rename / reset / delete) via shadcn DropdownMenu. */
export default function StorySandboxBranchMenu({
  branchId,
  busy,
  isSyncing,
  onCreate,
  onRename,
  onReset,
  onDelete,
}: StorySandboxBranchMenuProps) {
  const branchActionsDisabled = busy || isSyncing || !branchId

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="xs"
          aria-label="故事线操作"
          className="group"
        >
          管理
          <ChevronDownIcon className="opacity-50 transition-transform duration-200 group-data-[state=open]:rotate-180" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="min-w-40 [&_[data-slot=dropdown-menu-item]]:py-1 [&_[data-slot=dropdown-menu-item]]:text-xs [&_[data-slot=dropdown-menu-item]_svg:not([class*='size-'])]:size-3"
      >
        <DropdownMenuItem onClick={onCreate}>
          <Plus />
          新建故事线
        </DropdownMenuItem>
        <DropdownMenuItem disabled={!branchId} onClick={() => { if (branchId) onRename() }}>
          <Pencil />
          重命名
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          variant="destructive"
          disabled={branchActionsDisabled}
          onClick={() => void onReset()}
        >
          <RotateCcw />
          重置当前故事线
        </DropdownMenuItem>
        <DropdownMenuItem
          variant="destructive"
          disabled={branchActionsDisabled}
          onClick={() => void onDelete()}
        >
          <Trash2 />
          删除当前故事线
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
