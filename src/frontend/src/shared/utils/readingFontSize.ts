export type ReadingFontSize = 'small' | 'default' | 'large' | 'xlarge'

const STORAGE_KEY = 'chronos.readingFontSize'
const CSS_VAR = '--reading-font-size'

export const READING_FONT_SIZE_PX: Record<ReadingFontSize, number> = {
  small: 13,
  default: 14,
  large: 16,
  xlarge: 18,
}

/** Read the user's last-chosen reading font size; null if unset or invalid. */
export function readStoredReadingFontSize(): ReadingFontSize | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'small' || v === 'default' || v === 'large' || v === 'xlarge') return v
  } catch {
    /* Ignored when localStorage is not available */
  }
  return null
}

/** First-screen size: local preference, else the default (14px, matches the old fixed text-sm). */
export function resolveInitialReadingFontSize(): ReadingFontSize {
  return readStoredReadingFontSize() ?? 'default'
}

export function applyReadingFontSize(size: ReadingFontSize): void {
  document.documentElement.style.setProperty(CSS_VAR, `${READING_FONT_SIZE_PX[size]}px`)
}

export function persistReadingFontSize(size: ReadingFontSize): void {
  try {
    localStorage.setItem(STORAGE_KEY, size)
  } catch {
    /* neglect */
  }
}
