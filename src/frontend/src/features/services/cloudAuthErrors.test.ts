import { describe, expect, it } from 'vitest'
import { cloudAuthErrorMessage } from '@/features/services/cloudAuthErrors'

describe('cloudAuthErrorMessage', () => {
  it('uses the generic message when no error code is provided', () => {
    expect(cloudAuthErrorMessage(undefined)).toBe('操作失败，请重试')
  })

  it('maps known cloud auth errors to Chinese messages', () => {
    expect(cloudAuthErrorMessage('OAUTH_TIMEOUT')).toBe('登录超时，请重试')
  })

  it('includes unknown error codes for diagnostics', () => {
    expect(cloudAuthErrorMessage('UNEXPECTED_ERROR')).toBe('操作失败（UNEXPECTED_ERROR）')
  })
})
