/** 成稿字数：去空白后的字符数（与网文平台「字数」口径一致）。 */
export function countManuscriptChars(content: string): number {
  return content.replace(/\s/g, '').length
}
