/**
 * Engineering Assistant - Main Application
 *
 * A desktop app for querying engineering documents.
 */
import { useState, useEffect, useCallback } from 'react'
import { listen } from '@tauri-apps/api/event'
import { setBackendPort, getApiBase } from './api'
import { Layout, Menu, Button } from 'antd'
import { MessageOutlined, BookOutlined, CalendarOutlined, SettingOutlined, PlusOutlined, DeleteOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import { open } from '@tauri-apps/plugin-shell'
import ChatView from './views/ChatView'
import KnowledgeBaseView from './views/KnowledgeBaseView'
import ConfigView from './views/ConfigView'
import MeetingsView from './views/MeetingsView'
import './App.css'

const { Sider, Content } = Layout

type ViewType = 'chat' | 'knowledge' | 'meetings' | 'config'

const menuItems = [
  {
    key: 'chat',
    icon: <MessageOutlined />,
    label: '聊天',
  },
  {
    key: 'knowledge',
    icon: <BookOutlined />,
    label: '知识库',
  },
  {
    key: 'meetings',
    icon: <CalendarOutlined />,
    label: '会议纪要',
  },
  {
    key: 'config',
    icon: <SettingOutlined />,
    label: '设置',
  },
]

interface SessionInfo {
  id: string
  title: string
  created_at: string
  message_count: number
}


function App() {
  const [currentView, setCurrentView] = useState<ViewType>('chat')

  // Listen for dynamic backend port from Tauri
  useEffect(() => {
    let unlisten: (() => void) | undefined
    listen<number>('backend-port', (event) => {
      setBackendPort(event.payload)
    }).then(fn => { unlisten = fn }).catch(() => {/* not in Tauri */ })
    return () => { unlisten?.() }
  }, [])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessions, setSessions] = useState<SessionInfo[]>([])

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch(`${getApiBase()}/sessions`)
      if (res.ok) {
        setSessions(await res.json())
      }
    } catch { /* backend may not be running yet */ }
  }, [])

  // Wait for backend to be ready, then load sessions
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      while (!cancelled) {
        try {
          const res = await fetch(`${getApiBase()}/health`)
          if (res.ok) break
        } catch { /* not ready yet */ }
        await new Promise(r => setTimeout(r, 1000))
      }
      if (!cancelled) fetchSessions()
    }
    poll()
    return () => { cancelled = true }
  }, [fetchSessions])

  // Also refresh when switching to chat (in case new sessions were created elsewhere)
  useEffect(() => {
    if (currentView === 'chat') fetchSessions()
  }, [fetchSessions, currentView])

  const handleNewChat = useCallback(async (): Promise<string> => {
    try {
      const res = await fetch(`${getApiBase()}/sessions`, { method: 'POST' })
      if (res.ok) {
        const session = await res.json()
        setSessionId(session.id)
        fetchSessions()
        return session.id
      }
    } catch { /* ignore */ }
    return ''
  }, [fetchSessions])

  const handleDeleteSession = useCallback(async (id: string) => {
    try {
      await fetch(`${getApiBase()}/sessions/${id}`, { method: 'DELETE' })
      if (id === sessionId) {
        setSessionId(null)
      }
      fetchSessions()
    } catch { /* ignore */ }
  }, [sessionId, fetchSessions])

  const handleMenuClick = (e: { key: string }) => {
    setCurrentView(e.key as ViewType)
  }

  const openApiGuide = useCallback(async () => {
    const origin = window.location.origin; await open(`${origin}/docs/api-guide/index.html`)
  }, [])

  return (
    <Layout className="app-layout">
      <Sider width={200} className="app-sider" theme="light">
        <div className="sider-header">
          <h1>工程设计工作台</h1>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[currentView]}
          onClick={handleMenuClick}
          items={menuItems}
          className="sider-menu"
        />
        <div className="sider-body">
          {currentView === 'chat' && (
            <div className="session-section">
              <div className="session-header">
                <span className="session-header-title">历史会话</span>
                <Button
                  type="text"
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={handleNewChat}
                  title="新建对话"
                />
              </div>
              <div className="session-list">
                {sessions.map((s) => (
                  <div
                    key={s.id}
                    className={`session-item${s.id === sessionId ? ' active' : ''}`}
                    onClick={() => { setSessionId(s.id); setCurrentView('chat') }}
                  >
                    <span className="session-item-title" title={s.title}>
                      {s.title || '新对话'}
                    </span>
                    <Button
                      type="text"
                      size="small"
                      className="session-delete-btn"
                      icon={<DeleteOutlined />}
                      onClick={(e) => { e.stopPropagation(); handleDeleteSession(s.id) }}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="sider-bottom-menu">
          <div className="sider-menu-item" onClick={openApiGuide}>
            <QuestionCircleOutlined />
            <span>文档</span>
          </div>
        </div>
      </Sider>

      <Layout className="main-layout">
        <Content className="main-content">
          {currentView === 'chat' && <ChatView sessionId={sessionId} onNewChat={handleNewChat} />}
          {currentView === 'knowledge' && <KnowledgeBaseView />}
          {currentView === 'meetings' && <MeetingsView />}
          {currentView === 'config' && <ConfigView />}
        </Content>
      </Layout>
    </Layout>
  )
}

export default App
