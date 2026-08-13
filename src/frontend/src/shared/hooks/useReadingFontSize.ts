import { useCallback, useState } from 'react'
import {
  applyReadingFontSize,
  persistReadingFontSize,
  resolveInitialReadingFontSize,
  type ReadingFontSize,
} from '@/shared/utils/readingFontSize'

export function useReadingFontSize() {
  const [size, setSizeState] = useState<ReadingFontSize>(resolveInitialReadingFontSize)

  const setSize = useCallback((next: ReadingFontSize) => {
    setSizeState(next)
    applyReadingFontSize(next)
    persistReadingFontSize(next)
  }, [])

  return { size, setSize }
}
