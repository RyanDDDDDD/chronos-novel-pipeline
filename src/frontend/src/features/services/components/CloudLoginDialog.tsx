import { useState } from 'react'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'

interface CloudLoginDialogProps {
  open: boolean
  onClose: () => void
}

export default function CloudLoginDialog({ open, onClose }: CloudLoginDialogProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (!open) return null

  const handlePasswordLogin = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const body = await res.json()
      if (!res.ok) {
        setError(body.error_code ?? '登录失败')
        return
      }
      onClose()
    } catch {
      setError('无法连接服务，请检查网络')
    } finally {
      setSubmitting(false)
    }
  }

  const handleGoogleLogin = async () => {
    setSubmitting(true)
    setError(null)
    try {
      await fetch('/api/auth/oauth/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: 'google' }),
      })
      // Completion arrives asynchronously via the cloud_auth_login_succeeded/failed WS event
      // (see cloudAuthSlice) -- this call only kicks off the browser flow, it doesn't wait.
      onClose()
    } catch {
      setError('无法启动登录流程，请检查网络')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-80 rounded-lg bg-[var(--c-surface)] p-6 shadow-float">
        <h2 className="mb-4 text-sm font-medium text-[var(--c-text)]">登录 Chronos 账号</h2>
        <div className="flex flex-col gap-2">
          <Input placeholder="邮箱" value={email} onChange={(e) => setEmail(e.target.value)} />
          <Input type="password" placeholder="密码" value={password} onChange={(e) => setPassword(e.target.value)} />
          {error && <p className="text-xs text-red-600">{error}</p>}
          <Button onClick={handlePasswordLogin} disabled={submitting}>登录</Button>
          <Button variant="ghost" onClick={handleGoogleLogin} disabled={submitting}>用 Google 登录</Button>
          <Button variant="ghost" onClick={onClose}>取消</Button>
        </div>
      </div>
    </div>
  )
}
