import React from 'react'
import { vi } from 'vitest'
import { TestProviders } from '@/test/testProviders'

if (typeof Element !== 'undefined') {
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = () => false
  }
  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = () => {}
  }
  if (!Element.prototype.releasePointerCapture) {
    Element.prototype.releasePointerCapture = () => {}
  }
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {}
  }
}

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

const matchMediaMock = vi.fn().mockImplementation((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: vi.fn(),
  removeListener: vi.fn(),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  dispatchEvent: vi.fn(),
}))
if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'matchMedia', { writable: true, configurable: true, value: matchMediaMock })
}
vi.stubGlobal('matchMedia', matchMediaMock)

vi.mock('@testing-library/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@testing-library/react')>()
  return {
    ...actual,
    render: (ui: React.ReactElement, options: Parameters<typeof actual.render>[1] = {}) => {
      const { wrapper: InnerWrapper, ...rest } = options
      const Wrapper = ({ children }: { children: React.ReactNode }) => (
        <TestProviders>
          {InnerWrapper ? <InnerWrapper>{children}</InnerWrapper> : children}
        </TestProviders>
      )
      return actual.render(ui, { ...rest, wrapper: Wrapper })
    },
  }
})
