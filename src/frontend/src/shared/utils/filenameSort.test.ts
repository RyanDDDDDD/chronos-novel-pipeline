import { describe, expect, it } from 'vitest'
import { compareNaturalFilenames, sortFilesByNaturalFilename } from './filenameSort'

describe('compareNaturalFilenames', () => {
  it('orders numeric segments naturally', () => {
    expect(compareNaturalFilenames('1.jpg', '2.jpg')).toBeLessThan(0)
    expect(compareNaturalFilenames('2.jpg', '10.jpg')).toBeLessThan(0)
    expect(compareNaturalFilenames('10.jpg', '2.jpg')).toBeGreaterThan(0)
  })
})

describe('sortFilesByNaturalFilename', () => {
  it('returns files sorted by natural filename order', () => {
    const files = [
      new File(['c'], '10.jpg'),
      new File(['a'], '1.jpg'),
      new File(['b'], '2.jpg'),
    ]
    expect(sortFilesByNaturalFilename(files).map((f) => f.name)).toEqual(['1.jpg', '2.jpg', '10.jpg'])
  })
})
