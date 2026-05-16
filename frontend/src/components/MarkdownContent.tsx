/**
 * MarkdownContent - Markdown 渲染 + [引用:xxx] 可点击标签
 *
 * 支持：
 * - 标题、加粗、列表、代码块等标准 markdown
 * - [引用:文档名] 渲染为可点击的蓝色标签，点击跳转到原文位置
 */
import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import type { Citation } from '../types'
import './MarkdownContent.css'

interface Props {
  content: string
  citations?: Citation[]
  onCitationClick?: (citation: Citation) => void
}

/** 将 [引用:xxx] 替换为占位标记，让 ReactMarkdown 不吞掉。支持嵌套方括号。 */
function preprocessCitations(text: string): string {
  const result: string[] = []
  let i = 0
  while (i < text.length) {
    const rest = text.slice(i)
    const match = rest.match(/^\[(引用|来源)[:：]/)
    if (match) {
      let depth = 1
      let j = i + match[0].length
      while (j < text.length && depth > 0) {
        if (text[j] === '[') depth++
        else if (text[j] === ']') depth--
        j++
      }
      if (depth === 0) {
        const content = text.slice(i + match[0].length, j - 1)
        result.push(`%%CITATION:${content}%%`)
        i = j
        continue
      }
    }
    result.push(text[i])
    i++
  }
  return result.join('')
}

/** 从 React children 中提取纯文本 */
function childrenToText(children: React.ReactNode): string {
  if (typeof children === 'string') return children
  if (Array.isArray(children)) return children.map(childrenToText).join('')
  if (React.isValidElement<Record<string, React.ReactNode>>(children) && children.props.children) {
    return childrenToText(children.props.children)
  }
  return ''
}

/** 解析引用文本中的 doc_name 和 location 部分 */
function parseCitationText(text: string): { docName: string; location: string | null } {
  const sepIndex = text.indexOf('#')
  if (sepIndex === -1) return { docName: text, location: null }
  return {
    docName: text.slice(0, sepIndex),
    location: text.slice(sepIndex + 1),
  }
}

/** Normalize path separators for cross-platform comparison. */
const normPath = (s: string) => s.replace(/\\/g, '/')

/** Strip common file extensions for fuzzy name matching. */
const stripExt = (s: string) => s.replace(/\.(chm|pdf|html?|htm)$/i, '')

/** 通过 doc_name / location 匹配找到对应的 citation */
function findMatchingCitation(
  citationText: string,
  citations?: Citation[]
): Citation | null {
  if (!citations || citations.length === 0) return null

  const { docName, location } = parseCitationText(citationText)

  // 策略1：doc_name 精确匹配 + location 匹配
  if (location) {
    const exactBoth = citations.find(c =>
      c.doc_name === docName && c.location && normPath(c.location).includes(normPath(location))
    )
    if (exactBoth) return exactBoth

    // 策略1.5：location 包含页码（如"第14页"），按 page 精确匹配
    const pageMatch = location.match(/第\s*(\d+)\s*页/)
    if (pageMatch) {
      const targetPage = parseInt(pageMatch[1], 10)
      const pageExact = citations.find(c =>
        c.doc_name === docName && c.page === targetPage
      )
      if (pageExact) return pageExact
    }
  }

  // 策略2：doc_name 精确匹配
  const exactName = citations.find(c => c.doc_name === docName)
  if (exactName) return exactName

  // 策略3：引用文本与 citation 的 location 互相包含（CHM 场景）
  // LLM 可能输出 `[来源:规范名\path.html]` 而非标准的 `[来源:file.chm#path.html]`
  const normCite = normPath(citationText)
  const locationMatch = citations.find(c => {
    if (!c.location) return false
    const normLoc = normPath(c.location)
    return normCite.includes(normLoc) || normLoc.includes(normCite)
  })
  if (locationMatch) return locationMatch

  // 策略3.5：引用文本的路径首段匹配 doc_name（CHM 子目录名匹配）
  // 例如 "高层建筑混凝土结构技术规程/xxx.html" → 首段 "高层建筑混凝土结构技术规程"
  const pathParts = normCite.split('/')
  if (pathParts.length > 1) {
    const firstDir = pathParts[0]
    const chmNameMatch = citations.find(c =>
      stripExt(c.doc_name) === firstDir
    )
    if (chmNameMatch) return chmNameMatch
  }

  // 策略4：模糊匹配（去除扩展名后互相包含）
  const fuzzy = citations.find(c =>
    citationText.includes(c.doc_name) ||
    c.doc_name.includes(docName) ||
    stripExt(c.doc_name) === stripExt(docName) ||
    citationText.includes(stripExt(c.doc_name)) ||
    stripExt(c.doc_name).includes(normCite)
  )
  if (fuzzy) return fuzzy

  return null
}

/** 渲染处理后的文本，把占位标记还原为可点击标签 */
function CitationRenderer({
  text,
  citations,
  onCitationClick,
}: {
  text: string
  citations?: Citation[]
  onCitationClick?: (citation: Citation) => void
}) {
  const parts = text.split(/%%CITATION:([^%]+)%%/)
  if (parts.length === 1) return <>{text}</>

  return (
    <>
      {parts.map((part, i) => {
        if (i % 2 === 1) {
          const citation = findMatchingCitation(part, citations)
          const clickable = citation && onCitationClick
          return (
            <span
              key={i}
              className={`inline-citation${clickable ? ' clickable' : ''}`}
              title={part}
              onClick={clickable ? () => onCitationClick!(citation!) : undefined}
            >
              📎 {part}
            </span>
          )
        }
        return <React.Fragment key={i}>{part}</React.Fragment>
      })}
    </>
  )
}

export default function MarkdownContent({ content, citations, onCitationClick }: Props) {
  const processed = preprocessCitations(content)

  return (
    <div className="markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          p: ({ children }) => {
            const text = childrenToText(children)
            if (text.includes('%%CITATION:')) {
              return (
                <p>
                  <CitationRenderer
                    text={text}
                    citations={citations}
                    onCitationClick={onCitationClick}
                  />
                </p>
              )
            }
            return <p>{children}</p>
          },
          li: ({ children }) => {
            const text = childrenToText(children)
            if (text.includes('%%CITATION:')) {
              return (
                <li>
                  <CitationRenderer
                    text={text}
                    citations={citations}
                    onCitationClick={onCitationClick}
                  />
                </li>
              )
            }
            return <li>{children}</li>
          },
        }}
      >
        {processed}
      </ReactMarkdown>
    </div>
  )
}
