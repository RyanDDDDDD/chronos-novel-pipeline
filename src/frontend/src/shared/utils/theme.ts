export type Theme =
  | 'light'
  | 'dark'
  | 'sepia'
  | 'solarized-light'
  | 'solarized-dark'
  | 'dracula'

/** Display order + Chinese labels for the theme picker (SSOT). */
export const THEME_ORDER: Theme[] = [
  'light',
  'dark',
  'sepia',
  'solarized-light',
  'solarized-dark',
  'dracula',
]

export const THEME_LABELS: Record<Theme, string> = {
  light: '浅色默认',
  dark: '深色夜间',
  sepia: '暖黄护眼',
  'solarized-light': '薄雾日间',
  'solarized-dark': '薄雾夜间',
  dracula: '焦糖夜间',
}

const STORAGE_KEY = 'chronos.theme'
const THEME_CLASS_PREFIX = 'theme-'

export function isDarkTheme(theme: Theme): boolean {
  return theme === 'dark' || theme === 'solarized-dark' || theme === 'dracula'
}

/** Read the topic last selected by the user; if there is no record, return null.*/
export function readStoredTheme(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (
      v === 'light' ||
      v === 'dark' ||
      v === 'sepia' ||
      v === 'solarized-light' ||
      v === 'solarized-dark' ||
      v === 'dracula'
    ) return v
  } catch {
    /*Ignored when localStorage is not available*/
  }
  return null
}

/** First screen theme: local preferences > system prefers-color-scheme > light.*/
export function resolveInitialTheme(): Theme {
  const stored = readStoredTheme()
  if (stored) return stored
  if (typeof matchMedia !== 'undefined' && matchMedia('(prefers-color-scheme: dark)')?.matches) {
    return 'dark'
  }
  return 'light'
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement
  for (const c of [...root.classList]) {
    if (c.startsWith(THEME_CLASS_PREFIX)) root.classList.remove(c)
  }
  root.classList.add(`${THEME_CLASS_PREFIX}${theme}`)
  root.classList.toggle('dark', isDarkTheme(theme))
}

export function persistTheme(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    /*neglect*/
  }
}

export function toggleTheme(current: Theme): Theme {
  // Header now uses a dropdown; keep this for keyboard shortcuts/tests.
  return current === 'dark' ? 'light' : 'dark'
}
