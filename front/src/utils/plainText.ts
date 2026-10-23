/**
 * 列表与预览场景的纯文本摘要：去掉标题记号、行内代码、链接与 HTML 标签。
 * 目的：卡片里不出现 `## 学习目标` 这类原始 Markdown，观感更像成品。
 */
export function plainPreview(content?: string, limit = 200): string {
  if (!content) return ''
  return content
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/[*_`~>]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, limit)
}
