/**
 * Converts a subset of Markdown to clean HTML for help article rendering.
 * Supports headings, bold, italic, inline code, code blocks, tables (with
 * thead), ordered/unordered lists, and paragraphs.
 */
export function renderMarkdown(md: string): string {
  const lines = md.split('\n')
  const html: string[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Fenced code block
    if (line.startsWith('```')) {
      i++
      const codeLines: string[] = []
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(escapeHtml(lines[i]))
        i++
      }
      i++ // skip closing ```
      html.push(`<pre style="overflow-x:auto"><code>${codeLines.join('\n')}</code></pre>`)
      continue
    }

    // Headings
    if (line.startsWith('### ')) {
      html.push(`<h3>${inline(line.slice(4))}</h3>`)
      i++
      continue
    }
    if (line.startsWith('## ')) {
      html.push(`<h2>${inline(line.slice(3))}</h2>`)
      i++
      continue
    }
    if (line.startsWith('# ')) {
      html.push(`<h1>${inline(line.slice(2))}</h1>`)
      i++
      continue
    }

    // Table (lines starting with |)
    if (line.startsWith('|')) {
      const tableLines: string[] = []
      while (i < lines.length && lines[i].startsWith('|')) {
        tableLines.push(lines[i])
        i++
      }
      html.push(renderTable(tableLines))
      continue
    }

    // Unordered list (top-level only, starting with - or *)
    if (line.match(/^[-*] /)) {
      const items: string[] = []
      while (i < lines.length && lines[i].match(/^[-*] /)) {
        let item = inline(lines[i].replace(/^[-*] /, ''))
        i++
        // Collect indented sub-items as nested list
        const subItems: string[] = []
        while (i < lines.length && lines[i].match(/^\s+[-*] /)) {
          subItems.push(inline(lines[i].replace(/^\s+[-*] /, '')))
          i++
        }
        if (subItems.length > 0) {
          item += `<ul>${subItems.map((s) => `<li>${s}</li>`).join('')}</ul>`
        }
        items.push(item)
      }
      html.push(`<ul>${items.map((item) => `<li>${item}</li>`).join('')}</ul>`)
      continue
    }

    // Ordered list (supports indented sub-items as nested ul)
    if (line.match(/^\d+\. /)) {
      const items: string[] = []
      while (i < lines.length && lines[i].match(/^\d+\. /)) {
        let item = inline(lines[i].replace(/^\d+\. /, ''))
        i++
        // Collect indented sub-items as nested list
        const subItems: string[] = []
        while (i < lines.length && lines[i].match(/^\s+[-*] /)) {
          subItems.push(inline(lines[i].replace(/^\s+[-*] /, '')))
          i++
        }
        if (subItems.length > 0) {
          item += `<ul>${subItems.map((s) => `<li>${s}</li>`).join('')}</ul>`
        }
        items.push(item)
      }
      html.push(`<ol>${items.map((item) => `<li>${item}</li>`).join('')}</ol>`)
      continue
    }

    // Empty line — skip
    if (line.trim() === '') {
      i++
      continue
    }

    // Paragraph — collect consecutive non-empty, non-special lines
    const paraLines: string[] = []
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !lines[i].startsWith('#') &&
      !lines[i].startsWith('|') &&
      !lines[i].startsWith('```') &&
      !lines[i].match(/^[-*] /) &&
      !lines[i].match(/^\s+[-*] /) &&
      !lines[i].match(/^\d+\. /)
    ) {
      paraLines.push(lines[i])
      i++
    }
    html.push(`<p>${inline(paraLines.join(' '))}</p>`)
  }

  return html.join('\n')
}

/** Render inline markdown: bold, italic, inline code. */
function inline(text: string): string {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
}

/** Escape HTML special characters. */
function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** Render a markdown table with proper thead/tbody. */
function renderTable(lines: string[]): string {
  const rows = lines
    .filter((l) => !l.match(/^\|[\s-:|]+\|$/)) // skip separator row
    .map((l) =>
      l
        .split('|')
        .slice(1, -1) // remove leading/trailing empty from split
        .map((cell) => cell.trim()),
    )

  if (rows.length === 0) return ''

  const [header, ...body] = rows

  const thead = `<thead><tr>${header.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead>`
  const tbody =
    body.length > 0
      ? `<tbody>${body.map((row) => `<tr>${row.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody>`
      : ''

  return `<div style="overflow-x:auto"><table style="min-width:auto;font-size:inherit">${thead}${tbody}</table></div>`
}
