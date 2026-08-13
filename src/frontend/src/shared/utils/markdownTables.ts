/** GFM table delimited rows: Each cell contains only :--- alignment marks.*/
const TABLE_SEP_CELL = /^:?-{1,}:?$/

function isTableRow(line: string): boolean {
  const t = line.trim()
  return t.startsWith('|') && t.endsWith('|') && t.length > 2
}

function tableRowColumnCount(line: string): number | null {
  const t = line.trim()
  if (!isTableRow(t)) return null
  const cells = t.split('|').slice(1, -1)
  return cells.length > 0 ? cells.length : null
}

/** Inline multi-row table: Use the `| |` demarcation between rows to infer the number of the first row; for a single row, count the entire row.*/
function inferInlineTableColumnCount(t: string): number | null {
  const boundary = t.match(/\|\s*\|\s*\S/)
  if (boundary && boundary.index !== undefined) {
    const firstRow = t.slice(0, boundary.index + 1).trim()
    return tableRowColumnCount(firstRow)
  }
  return tableRowColumnCount(t)
}

/** Delimited rows → number of columns; non-delimited rows → null.*/
export function tableSeparatorColumnCount(line: string): number | null {
  const t = line.trim()
  if (!isTableRow(t)) return null
  const cells = t.split('|').slice(1, -1).map((c) => c.trim())
  if (cells.length === 0 || !cells.every((c) => TABLE_SEP_CELL.test(c))) return null
  return cells.length
}

function formatTableRow(cells: string[]): string {
  return `| ${cells.join(' | ')} |`
}

function makeSeparatorRow(cols: number): string {
  return formatTableRow(Array.from({ length: cols }, () => '---'))
}

/** Cut out a row of GFM table from the beginning of the row with a fixed number of columns; the number of columns is inferred from the first row.*/
function extractTableRow(text: string, start: number, ncol: number): { row: string; end: number } | null {
  let i = start
  while (i < text.length && text[i] !== '|') i++
  if (i >= text.length) return null

  i++ //Skip start of line |
  const cells: string[] = []
  for (let c = 0; c < ncol; c++) {
    const pipeIdx = text.indexOf('|', i)
    if (pipeIdx === -1) return null
    cells.push(text.slice(i, pipeIdx).trim())
    i = pipeIdx + 1
  }
  return { row: formatTableRow(cells), end: i }
}

/**
 *LLM often squeezes multi-line tables into one row: `| h1 | h2 | | d1 | d2 |` → Split into multiple rows according to the number of first rows and columns.
 */
export function splitInlineTableRows(line: string): string[] {
  const t = line.trim()
  if (!isTableRow(t)) return [line]

  const ncol = inferInlineTableColumnCount(t)
  if (ncol === null || ncol === 0) return [line]

  const rows: string[] = []
  let pos = 0
  while (pos < t.length) {
    const rest = t.slice(pos).trimStart()
    if (!rest.startsWith('|')) break
    pos += t.slice(pos).length - rest.length
    const parsed = extractTableRow(t, pos, ncol)
    if (!parsed) break
    rows.push(parsed.row)
    pos = parsed.end
    while (pos < t.length && /\s/.test(t[pos]!)) pos++
  }

  return rows.length > 1 ? rows : [line]
}

/**
 *Fix common GFM table mistakes made by LLM:
 *- Multiple rows of tables squeezed into one row → split rows
 *- There is a missing separator line between the header and the data row → Insert ---
 *- Missing header above the separated row → insert placeholder header
 */
export function repairMarkdownTables(md: string): string {
  const lines = md.split('\n').flatMap((line) => splitInlineTableRows(line))
  const out: string[] = []
  /** Whether the current table block already has GFM separated rows (only one row between table header and data).*/
  let blockHasSep = false

  for (const line of lines) {
    const trimmed = line.trim()
    const sepCols = tableSeparatorColumnCount(line)
    const isRow = isTableRow(trimmed)

    if (!isRow) {
      blockHasSep = false
    } else if (sepCols !== null) {
      blockHasSep = true
    } else {
      const prev = out[out.length - 1]?.trim() ?? ''
      if (isTableRow(prev) && tableSeparatorColumnCount(prev) === null && !blockHasSep) {
        const ncol = tableRowColumnCount(prev)
        if (ncol !== null && ncol > 0) {
          out.push(makeSeparatorRow(ncol))
          blockHasSep = true
        }
      }
    }

    if (sepCols !== null) {
      const prev = out[out.length - 1]?.trim() ?? ''
      const prevIsHeader =
        isTableRow(prev) && tableSeparatorColumnCount(prev) === null
      if (!prevIsHeader) {
        out.push(formatTableRow(Array.from({ length: sepCols }, (_, i) => `列${i + 1}`)))
      }
    }
    out.push(line)
  }
  return out.join('\n')
}
