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
  if (React.isValidElement(children) && children.props.children) {
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
      c.doc_name === docName && c.location && c.location.includes(location)
    )
    if (exactBoth) return exactBoth
  }

  // 策略2：doc_name 精确匹配
  const exactName = citations.find(c => c.doc_name === docName)
  if (exactName) return exactName

  // 策略3：引用文本匹配 location（CHM 引用中引用文本常是 location 名而非 doc_name）
  const locationMatch = citations.find(c =>
    c.location && citationText.includes(c.location)
  )
  if (locationMatch) return locationMatch

  // 策略4：引用文本包含 doc_name
  const fuzzy = citations.find(c =>
    citationText.includes(c.doc_name) || c.doc_name.includes(docName)
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
        remarkPlugins={[remarkGfm]}
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
