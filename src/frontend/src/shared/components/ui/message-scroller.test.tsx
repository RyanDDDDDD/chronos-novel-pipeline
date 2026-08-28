import React from 'react'
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import {
  MessageScrollerProvider,
  MessageScroller,
  MessageScrollerViewport,
  MessageScrollerContent,
} from './message-scroller'

describe('MessageScrollerViewport', () => {
  // Regression: `data-autoscrolling:scrollbar-none` toggled the scrollbar off during autoscroll.
  // With this app's classic (space-taking) scrollbars that collapses the reserved gutter, and
  // while pinned to the bottom the resulting width change reflows text every frame -> the
  // ResizeObserver re-fires autoscroll -> the toggle loops -> the chat box flickers. Scrolling
  // up (free mode, no autoscroll) stopped it. Keep the scrollbar visible during autoscroll.
  it('does not hide the scrollbar while autoscrolling', () => {
    const { container } = render(
      <MessageScrollerProvider autoScroll defaultScrollPosition="end">
        <MessageScroller>
          <MessageScrollerViewport>
            <MessageScrollerContent />
          </MessageScrollerViewport>
        </MessageScroller>
      </MessageScrollerProvider>,
    )
    const viewport = container.querySelector('[data-slot="message-scroller-viewport"]')
    expect(viewport).not.toBeNull()
    expect(viewport?.className).not.toContain('scrollbar-none')
  })
})
