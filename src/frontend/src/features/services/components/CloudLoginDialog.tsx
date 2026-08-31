import { useState } from 'react'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { cloudAuthErrorMessage as errorMessage } from '@/features/services/cloudAuthErrors'

interface CloudLoginDialogProps {
  open: boolean
  onClose: () => void
}

type DialogMode = 'login' | 'register' | 'confirm'

export default function CloudLoginDialog({ open, onClose }: CloudLoginDialogProps) {
  const [mode, setMode] = useState<DialogMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [confirmationCode, setConfirmationCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (!open) return null

  const resetToLogin = () => {
    setMode('login')
    setConfirmPassword('')
    setConfirmationCode('')
    setError(null)
  }

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
        setError(errorMessage(body.error_code))
        return
      }
      onClose()
    } catch {
      setError(errorMessage('NETWORK_ERROR'))
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
      setError(errorMessage('NETWORK_ERROR'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleRegister = async () => {
    setError(null)
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致')
      return
    }
    setSubmitting(true)
    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const body = await res.json()
      if (!res.ok) {
        setError(errorMessage(body.error_code))
        return
      }
      setMode('confirm')
    } catch {
      setError(errorMessage('NETWORK_ERROR'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleConfirm = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const confirmRes = await fetch('/api/auth/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, confirmation_code: confirmationCode }),
      })
      const confirmBody = await confirmRes.json()
      if (!confirmRes.ok) {
        setError(errorMessage(confirmBody.error_code))
        return
      }
      // Confirmed -- log in immediately with the same credentials rather than making the
      // user re-enter them on a fresh login screen.
      const loginRes = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const loginBody = await loginRes.json()
      if (!loginRes.ok) {
        setError(errorMessage(loginBody.error_code))
        return
      }
      onClose()
    } catch {
      setError(errorMessage('NETWORK_ERROR'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-80 rounded-lg bg-[var(--c-surface)] p-6 shadow-float">
        {mode === 'login' && (
          <>
            <h2 className="mb-4 text-sm font-medium text-[var(--c-text)]">登录 Chronos 账号</h2>
            <div className="flex flex-col gap-2">
              <Input placeholder="邮箱" value={email} onChange={(e) => setEmail(e.target.value)} />
              <Input type="password" placeholder="密码" value={password} onChange={(e) => setPassword(e.target.value)} />
              {error && <p className="text-xs text-red-600">{error}</p>}
              <Button onClick={handlePasswordLogin} disabled={submitting}>登录</Button>
              <Button variant="ghost" onClick={handleGoogleLogin} disabled={submitting}>用 Google 登录</Button>
              <button
                type="button"
                className="text-xs text-[var(--c-accent)] hover:underline"
                onClick={() => { setMode('register'); setError(null) }}
              >
                没有账号？注册
              </button>
              <Button variant="ghost" onClick={onClose}>取消</Button>
            </div>
          </>
        )}

        {mode === 'register' && (
          <>
            <h2 className="mb-4 text-sm font-medium text-[var(--c-text)]">注册 Chronos 账号</h2>
            <div className="flex flex-col gap-2">
              <Input placeholder="邮箱" value={email} onChange={(e) => setEmail(e.target.value)} />
              <Input type="password" placeholder="密码（至少 8 位，含大小写字母和数字）" value={password} onChange={(e) => setPassword(e.target.value)} />
              <Input type="password" placeholder="确认密码" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
              {error && <p className="text-xs text-red-600">{error}</p>}
              <Button onClick={handleRegister} disabled={submitting}>注册</Button>
              <button type="button" className="text-xs text-[var(--c-accent)] hover:underline" onClick={resetToLogin}>
                返回登录
              </button>
            </div>
          </>
        )}

        {mode === 'confirm' && (
          <>
            <h2 className="mb-4 text-sm font-medium text-[var(--c-text)]">验证邮箱</h2>
            <p className="mb-2 text-xs text-[var(--c-text-secondary)]">验证码已发送到 {email}，请查收并输入</p>
            <div className="flex flex-col gap-2">
              <Input placeholder="验证码" value={confirmationCode} onChange={(e) => setConfirmationCode(e.target.value)} />
              {error && <p className="text-xs text-red-600">{error}</p>}
              <Button onClick={handleConfirm} disabled={submitting}>确认</Button>
              <button type="button" className="text-xs text-[var(--c-accent)] hover:underline" onClick={resetToLogin}>
                返回登录
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
