import { useCallback, useState } from 'react'
import {
  applyTheme,
  persistTheme,
  resolveInitialTheme,
  toggleTheme,
  isDarkTheme,
  type Theme,
} from '@/shared/utils/theme'

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(resolveInitialTheme)

  const setThemeMode = useCallback((next: Theme) => {
    setTheme(next)
    applyTheme(next)
    persistTheme(next)
  }, [])

  const toggle = useCallback(() => {
    setTheme(prev => {
      const next = toggleTheme(prev)
      applyTheme(next)
      persistTheme(next)
      return next
    })
  }, [])

  return { theme, darkMode: isDarkTheme(theme), setTheme: setThemeMode, toggle }
}
