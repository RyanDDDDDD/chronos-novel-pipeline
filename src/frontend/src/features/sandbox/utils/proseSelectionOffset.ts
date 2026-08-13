const BLOCK_TAGS = new Set(['P', 'LI', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TR', 'HR', 'BLOCKQUOTE'])

function isBlockElement(node: Node): node is Element {
  return node.nodeType === Node.ELEMENT_NODE && BLOCK_TAGS.has((node as Element).tagName)
}

/** Reconstructs the plain text a prose bubble's rendered DOM represents, inserting `\n\n`
 * between block-level element boundaries -- react-markdown's rendered <p>/<li>/etc. children
 * don't carry that separator in their own textContent, but the raw markdown source they came
 * from did. Used both to get a bubble's full plain text and, via computeSelectionOffset, to
 * locate a selection's start within it. */
export function reconstructPlainText(container: Node): string {
  let text = ''
  let pendingBlockBreak = false
  const walker = document.createTreeWalker(
    container, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT,
  )
  let node: Node | null = walker.nextNode()
  while (node) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (pendingBlockBreak && text.length > 0) text += '\n\n'
      pendingBlockBreak = false
      text += node.textContent ?? ''
    } else if (isBlockElement(node)) {
      pendingBlockBreak = true
    }
    node = walker.nextNode()
  }
  return text
}

/** Character offset of `range`'s start point within `container`'s reconstructed plain text
 * (see reconstructPlainText) -- computed by cloning the sub-range from the container's start
 * to the selection's start and reconstructing *that* fragment's plain text, so it stays
 * consistent with the full-text reconstruction. */
export function computeSelectionOffset(container: Node, range: Range): number {
  const preRange = document.createRange()
  preRange.selectNodeContents(container)
  preRange.setEnd(range.startContainer, range.startOffset)
  return reconstructPlainText(preRange.cloneContents()).length
}
