import { useEffect, useState, type ReactNode } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { UserRound } from 'lucide-react'
import CloudLoginDialog from '@/features/services/components/CloudLoginDialog'
import { loginStatusHydrated } from '@/features/services/store/cloudAuthSlice'
import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import type { AppDispatch, RootState } from '@/shared/store/store'

// Cloud-account control for the novel rail. Owns the login dialog, the account row (both rail
// states), and the app-wide GET /api/auth/status hydration -- so login state is populated on
// every page load, not only when the service-config page happens to be mounted. Login
// success / failure / logout toasts are handled by the global store listener, not here; the
// slice flips isLoggedIn off the cloud_auth_logged_out WS event the backend broadcasts.
export default function CloudAuthControl({ collapsed }: { collapsed: boolean }) {
  const dispatch = useDispatch<AppDispatch>()
  const isLoggedIn = useSelector((s: RootState) => s.cloudAuth.isLoggedIn)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    void fetch('/api/auth/status')
      .then((res) => res.json())
      .then((body: { logged_in: boolean }) => dispatch(loginStatusHydrated(body.logged_in)))
      .catch(() => {})
  }, [dispatch])

  const openLogin = () => {
    setMenuOpen(false)
    setDialogOpen(true)
  }
  const logout = () => {
    setMenuOpen(false)
    void fetch('/api/auth/logout', { method: 'POST' }).catch(() => {})
  }

  const label = isLoggedIn ? '已登录' : '未登录'
  const dialog = <CloudLoginDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />

  // When logged in, the trigger opens a re-login / logout menu; when logged out it opens the
  // dialog directly (a one-item menu would just be friction).
  const loggedInMenu = (trigger: ReactNode) => (
    <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent side={collapsed ? 'right' : 'top'} align="end" className="w-32">
        <DropdownMenuItem onClick={openLogin}>重新登录</DropdownMenuItem>
        <DropdownMenuItem onClick={logout}>登出</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )

  if (collapsed) {
    const iconButton = (
      <Button
        type="button"
        variant="ghost"
        title={`Chronos 账号 · ${label}`}
        aria-label={`Chronos 账号 · ${label}`}
        onClick={isLoggedIn ? undefined : openLogin}
        className="relative size-8 min-w-8 min-h-8 rounded-lg text-[color:var(--c-text-faint)] hover:text-[color:var(--c-text-secondary)] flex items-center justify-center"
      >
        <UserRound size={16} aria-hidden />
        <span
          aria-hidden
          className={`absolute -right-0.5 -top-0.5 size-2 rounded-full ${isLoggedIn ? 'bg-emerald-500' : 'bg-slate-300'}`}
        />
      </Button>
    )
    return (
      <div className="w-full flex justify-center shrink-0 py-1">
        {isLoggedIn ? loggedInMenu(iconButton) : iconButton}
        {dialog}
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between gap-2 px-2.5 py-1.5 text-[11px] text-[color:var(--c-text-muted)]">
      <span className="flex items-center gap-1.5 truncate">
        <span
          aria-hidden
          className={`inline-block size-2 rounded-full shrink-0 ${isLoggedIn ? 'bg-emerald-500' : 'bg-slate-300'}`}
        />
        <UserRound size={12} className="shrink-0" aria-hidden />
        {label}
      </span>
      {isLoggedIn ? (
        loggedInMenu(
          <button type="button" className="shrink-0 text-[var(--c-accent)] hover:underline">
            账号
          </button>,
        )
      ) : (
        <button type="button" onClick={openLogin} className="shrink-0 text-[var(--c-accent)] hover:underline">
          登录
        </button>
      )}
      {dialog}
    </div>
  )
}
