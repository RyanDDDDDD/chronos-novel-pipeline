/** Natural-order filename compare (1.jpg < 2.jpg < 10.jpg). */
export function compareNaturalFilenames(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })
}

/** Return a new array of files sorted by filename in natural order. */
export function sortFilesByNaturalFilename(files: File[]): File[] {
  return [...files].sort((a, b) => compareNaturalFilenames(a.name, b.name))
}
