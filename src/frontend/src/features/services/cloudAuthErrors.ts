// error_code -> Chinese message. chronos owns this mapping because the cloud service's
// message field is English/diagnostic-only and must never be shown to users.
export const ERROR_MESSAGES: Record<string, string> = {
  INVALID_CREDENTIALS: '邮箱或密码不正确',
  USER_NOT_CONFIRMED: '账号尚未验证，请先完成邮箱验证码验证',
  EMAIL_ALREADY_EXISTS: '该邮箱已注册，请直接登录',
  INVALID_PASSWORD: '密码不符合要求（至少 8 位，包含大小写字母和数字）',
  CODE_MISMATCH: '验证码不正确',
  CODE_EXPIRED: '验证码已过期，请重新注册获取新验证码',
  NOT_CONFIGURED: '云端登录服务尚未配置',
  NETWORK_ERROR: '无法连接云端服务，请检查网络',
  OAUTH_TIMEOUT: '登录超时，请重试',
  OAUTH_CALLBACK_PORT_BUSY: '本地端口 53214 被占用，请关闭占用该端口的程序后重试',
  OAUTH_STATE_MISMATCH: '登录校验失败，请重新登录',
  OAUTH_CODE_INVALID: '登录授权失败，请重试',
  OAUTH_START_MALFORMED: '登录失败，请重试',
  OAUTH_BROWSER_FAILED: '无法打开系统浏览器，请检查默认浏览器设置',
  OAUTH_FAILED: '登录失败，请重试',
  RATE_LIMITED: '操作太频繁，请稍后再试',
  INVALID_PARAMETER: '输入格式不正确',
  PASSWORD_RESET_REQUIRED: '该账号需要重置密码，请通过邮箱找回密码',
}

export function cloudAuthErrorMessage(code: string | undefined): string {
  if (!code) return '操作失败，请重试'
  return ERROR_MESSAGES[code] ?? `操作失败（${code}）`
}
