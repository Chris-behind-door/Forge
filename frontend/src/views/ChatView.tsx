/**
 * ChatView - 聊天查询界面
 *
 * 功能：
 * - 输入问题，通过 LLM Agent 查询知识库
 * - 显示 AI 回答和内联可点击引用标签
 * - loading 状态提示（正在检索知识库...）
 * - 支持会话历史（通过 sessionId prop）
 *
 * 交互：
 * - Enter 发送消息
 * - Shift+Enter 换行
 */
import { useState, useCallback, useEffect, useRef } from 'react'
import { Input, Button, Card, Spin, message, Select } from 'antd'
import { SendOutlined, PlusOutlined } from '@ant-design/icons'
import { open } from '@tauri-apps/plugin-shell'
import { listen } from '@tauri-apps/api/event'
import MarkdownContent from '../components/MarkdownContent'
import type { Citation } from '../types'
import { useProjects } from '../hooks/useProjects'
import type { Project } from '../types'
import './ChatView.css'

interface Message {
  id: number
  role: 'user' | 'assistant' | 'loading'
  content: string
  citations?: Citation[]
  rounds?: number
}

interface ChatViewProps {
  sessionId: string | null
  onNewChat: () => Promise<string>
  projects?: Project[]
}

let messageId = 0
const nextMessageId = () => ++messageId

import { getApiBase } from '../api'

const { TextArea } = Input

function ChatView({ sessionId, onNewChat, projects: externalProjects }: ChatViewProps) {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [ipcToken, setIpcToken] = useState<string | null>(null)
  const [selectedProjectId, setSelectedProjectId] = useState<string>('__general__')
  const localProjects = useProjects()
  const projects = externalProjects || localProjects.projects

  useEffect(() => {
    const unlisten = listen<string>('ipc-token', (event) => {
      setIpcToken(event.payload)
    })
    return () => { unlisten.then((fn) => fn()) }
  }, [])

  // Track whether we're in the middle of sending (prevent sessionId effect from wiping)
  const sendingRef = useRef(false)

  // Load session messages when sessionId changes (but NOT during send)
  useEffect(() => {
    if (!sessionId) {
      setMessages([])
      return
    }
    if (sendingRef.current) return // Don't overwrite messages while a query is in flight
    ;(async () => {
      try {
        const res = await fetch(`${getApiBase()}/sessions/${sessionId}`)
        if (res.ok) {
          const data = await res.json()
          const loaded: Message[] = (data.messages || []).map(
            (m: { role: string; content: string; rounds?: number; citations?: string }) => ({
              id: nextMessageId(),
              role: m.role as 'user' | 'assistant',
              content: m.content,
              rounds: m.rounds,
              citations: m.citations ? JSON.parse(m.citations) : undefined,
            })
          )
          setMessages(loaded)
        }
      } catch { /* ignore */ }
    })()
  }, [sessionId])

  /** 点击内联引用标签的处理 — 在浏览器中打开原文位置 */
  const handleCitationClick = useCallback(async (c: Citation) => {
    try {
      const res = await fetch(`${getApiBase()}/documents/${c.doc_id}/chunks/${c.chunk_index}`)
      if (!res.ok) throw new Error('获取 chunk 详情失败')
      const detail = await res.json()

      if (detail.file_type === 'chm') {
        const chmLocation = (detail.location || c.location || '').replace(/\\/g, '/')
        if (chmLocation && chmLocation.includes('/')) {
          const url = `${getApiBase()}/documents/${c.doc_id}/chm-html?` +
            new URLSearchParams({ path: chmLocation })
          open(url)
        } else {
          message.info('该引用暂无精确定位，请查阅原文')
        }
      } else if (detail.file_type === 'pdf') {
        let url = `${getApiBase()}/documents/${c.doc_id}/file`
        const page = detail.page ?? c.page
        if (page) url += `#page=${page}`
        open(url)
      } else {
        message.info('该引用暂无精确定位，请查阅原文')
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '打开引用失败')
    }
  }, [])

  const handleSend = useCallback(async () => {
    if (!input.trim()) return

    const userMsg: Message = { id: nextMessageId(), role: 'user', content: input }
    const loadingMsg: Message = { id: nextMessageId(), role: 'loading', content: '正在检索知识库...' }
    setMessages((prev) => [...prev, userMsg, loadingMsg])
    setInput('')
    sendingRef.current = true
    setLoading(true)

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (ipcToken) headers['Authorization'] = `Bearer ${ipcToken}`

      // Create session on first message if none exists
      let sid = sessionId
      if (!sid) {
        sid = await onNewChat()
      }

      const body: { question: string; session_id: string; project_id?: string } = { question: input, session_id: sid }
      if (selectedProjectId && selectedProjectId !== '__general__') body.project_id = selectedProjectId

      const response = await fetch(`${getApiBase()}/query`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => null)
        throw new Error(errData?.detail || `HTTP ${response.status}`)
      }

      const data = await response.json()
      const assistantMsg: Message = {
        id: nextMessageId(),
        role: 'assistant',
        content: data.answer,
        citations: data.citations || [],
        rounds: data.rounds || 0,
      }
      setMessages((prev) => [...prev.slice(0, -1), assistantMsg])
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : '未知错误'
      const errorMsg: Message = {
        id: nextMessageId(),
        role: 'assistant',
        content: `[错误] ${errMsg}`,
      }
      setMessages((prev) => [...prev.slice(0, -1), errorMsg])
    } finally {
      setLoading(false)
      sendingRef.current = false
    }
  }, [input, ipcToken, sessionId, selectedProjectId, onNewChat])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend]
  )

  return (
    <div className="chat-view">
      <div className="chat-header">
        <Button
          size="small"
          icon={<PlusOutlined />}
          onClick={onNewChat}
        >
          新对话
        </Button>
      </div>
      <div className="messages">
        {messages.length === 0 && (
          <div className="empty-state">
            <p>输入问题开始查询</p>
          </div>
        )}
        {messages.map((msg) => (
          <Card key={msg.id} className={`message ${msg.role}`} size="small">
            {msg.role === 'loading' ? (
              <div className="loading-message">
                <Spin size="small" />
                <span>{msg.content}</span>
              </div>
            ) : (
              <>
                <div className="message-role">
                  {msg.role === 'user' ? '👤 你' : '🤖 助手'}
                  {msg.rounds ? (
                    <span className="message-rounds">
                      （检索 {msg.rounds} 轮）
                    </span>
                  ) : null}
                </div>
                <MarkdownContent
                  content={msg.content}
                  citations={msg.citations}
                  onCitationClick={msg.citations?.length ? handleCitationClick : undefined}
                />
                {msg.role === 'assistant' && !msg.content.startsWith('[错误]') && (
                  <div className="ai-disclaimer">
                    本回复由AI生成，请验证其正确性
                  </div>
                )}
              </>
            )}
          </Card>
        ))}

      </div>

      <div className="input-area">
        <div style={{
          border: '1px solid #d9d9d9',
          borderRadius: 12,
          overflow: 'hidden',
          background: '#fff',
        }}>
          {/* 输入框区域 */}
          <TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入问题... (Enter 发送, Shift+Enter 换行)"
            autoSize={{ minRows: 3, maxRows: 8 }}
            disabled={loading}
            bordered={false}
            style={{ padding: '12px 16px 8px', resize: 'none' }}
          />
          {/* 底部工具栏 */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '4px 12px 8px',
          }}>
            <Select
              size="small"
              value={selectedProjectId}
              onChange={(v) => setSelectedProjectId(v)}
              style={{ minWidth: 120 }}
              options={[
                { value: '__general__', label: '📚 通用知识' },
                ...projects.map(p => ({ value: p.id, label: `📁 ${p.name}` })),
              ]}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              loading={loading}
              disabled={!input.trim()}
              size="small"
            >
              发送
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default ChatView
