/**
 * MeetingsView - 会议纪要管理界面（主布局）
 *
 * 只负责组装子组件，状态管理在子组件内部。
 * 包含异步导入队列的轮询机制。
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { Select, Modal, Form, Input, DatePicker, message, Empty } from 'antd'
import { getApiBase } from '../api'
import { useProjects } from '../hooks/useProjects'
import MeetingList from '../components/MeetingList'
import MeetingDetail from '../components/MeetingDetail'
import ImportMeetingModal from '../components/ImportMeetingModal'
import './MeetingsView.css'

interface Meeting {
  id: string
  project_id: string
  title: string
  date: string
  summary: string
  source_doc_id: string | null
  raw_text: string
  created_at: string
  status?: string
  error?: string
}

function MeetingsView() {
  const { projects } = useProjects()
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [meetings, setMeetings] = useState<Meeting[]>([])
  const [selectedMeeting, setSelectedMeeting] = useState<Meeting | null>(null)
  const [meetingsLoading, setMeetingsLoading] = useState(false)
  const [extractLoading, setExtractLoading] = useState(false)

  // New meeting modal
  const [newMeetingOpen, setNewMeetingOpen] = useState(false)
  const [meetingForm] = Form.useForm()

  // Import modal
  const [importOpen, setImportOpen] = useState(false)

  // Polling — use ref to avoid dependency issues
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const projectRef = useRef<string | null>(null)
  projectRef.current = selectedProjectId

  // -------- Data --------

  const fetchMeetings = useCallback(async (projectId: string, silent: boolean = false) => {
    if (!silent) setMeetingsLoading(true)
    try {
      const res = await fetch(`${getApiBase()}/projects/${projectId}/meetings`)
      if (res.ok) {
        const data = await res.json()
        setMeetings(data.sort((a: Meeting, b: Meeting) => a.date.localeCompare(b.date)))
      }
    } catch { /* ignore */ }
    if (!silent) setMeetingsLoading(false)
  }, [])

  useEffect(() => {
    if (selectedProjectId) {
      fetchMeetings(selectedProjectId)
      setSelectedMeeting(null)
    } else {
      setMeetings([])
      setSelectedMeeting(null)
    }
  }, [selectedProjectId, fetchMeetings])

  // -------- Polling for import status --------

  const startPolling = useCallback(() => {
    if (pollRef.current) return // already polling

    const poll = async () => {
      const pid = projectRef.current
      if (!pid) return
      try {
        const res = await fetch(`${getApiBase()}/projects/${pid}/meetings/import-status`)
        if (res.ok) {
          const data = await res.json()
          const hasAny = data.processing || (data.queued && data.queued.length > 0) || (data.failed && data.failed.length > 0)
          // Always refresh to pick up status changes
          const mtgRes = await fetch(`${getApiBase()}/projects/${pid}/meetings`)
          if (mtgRes.ok) {
            const mtgData = await mtgRes.json()
            const sorted = mtgData.sort((a: Meeting, b: Meeting) => a.date.localeCompare(b.date))
            setMeetings(sorted)
            // Update selected meeting
            setSelectedMeeting(prev => {
              if (!prev) return prev
              const updated = sorted.find((m: Meeting) => m.id === prev.id)
              return updated || prev
            })
            // If all active, stop polling
            if (!hasAny) {
              if (pollRef.current) {
                clearInterval(pollRef.current)
                pollRef.current = null
              }
            }
          }
        }
      } catch { /* ignore */ }
    }

    // Poll immediately, then every 2 seconds
    poll()
    pollRef.current = setInterval(poll, 2000)
  }, [])

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => { stopPolling() }
  }, [stopPolling])

  // Auto-detect non-active meetings and start/stop polling
  useEffect(() => {
    const hasNonActive = meetings.some(m => m.status && m.status !== 'active')
    if (hasNonActive) {
      startPolling()
    }
  }, [meetings, startPolling])

  // -------- Handlers --------

  const handleSelectMeeting = useCallback((meeting: Meeting) => {
    setSelectedMeeting(meeting)
  }, [])

  const handleDeleteMeeting = async (meetingId: string) => {
    try {
      const res = await fetch(`${getApiBase()}/meetings/${meetingId}`, { method: 'DELETE' })
      if (res.ok) {
        message.success('会议已删除')
        if (selectedMeeting?.id === meetingId) setSelectedMeeting(null)
        if (selectedProjectId) fetchMeetings(selectedProjectId)
      } else message.error('删除失败')
    } catch { message.error('删除失败') }
  }

  const handleRetryImport = async (meetingId: string) => {
    try {
      const res = await fetch(`${getApiBase()}/meetings/${meetingId}/retry-import`, { method: 'POST' })
      if (res.ok) {
        message.success('已重新加入处理队列')
        if (selectedProjectId) fetchMeetings(selectedProjectId)
        startPolling()
      } else {
        const err = await res.json()
        message.error(err.detail || '重试失败')
      }
    } catch { message.error('重试失败') }
  }

  const handleCreateMeeting = async () => {
    try {
      const values = await meetingForm.validateFields()
      if (!selectedProjectId) return
      const dayjs = (await import('dayjs')).default
      const res = await fetch(`${getApiBase()}/projects/${selectedProjectId}/meetings`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: values.title,
          date: values.date?.format('YYYY-MM-DD') || dayjs().format('YYYY-MM-DD'),
          raw_text: values.raw_text || '',
        }),
      })
      if (res.ok) { message.success('会议已创建'); setNewMeetingOpen(false); meetingForm.resetFields(); fetchMeetings(selectedProjectId) }
    } catch { /* validation */ }
  }

  const handleImported = useCallback(() => {
    // Refresh silently (no global loading spinner) and start polling
    if (selectedProjectId) {
      fetchMeetings(selectedProjectId, true)
      startPolling()
    }
  }, [selectedProjectId, fetchMeetings, startPolling])

  return (
    <div className="meetings-view">
      <div className="meetings-sidebar">
        <div className="sidebar-section">
          <div className="sidebar-section-header"><span>项目</span></div>
          <Select style={{ width: '100%' }} placeholder="选择项目" value={selectedProjectId}
            onChange={setSelectedProjectId} options={projects.map(p => ({ label: p.name, value: p.id }))} />
        </div>
        <div className="sidebar-section">
          <MeetingList
            meetings={meetings} selectedMeetingId={selectedMeeting?.id ?? null}
            loading={meetingsLoading} hasProject={!!selectedProjectId}
            onSelect={handleSelectMeeting} onDelete={handleDeleteMeeting}
            onNewMeeting={() => setNewMeetingOpen(true)}
            onImport={() => setImportOpen(true)}
            onRetryImport={handleRetryImport}
          />
        </div>
      </div>

      <div className="meetings-detail">
        {!selectedMeeting ? (
          <Empty description="请从左侧选择一场会议" className="detail-empty" />
        ) : (
          <MeetingDetail
            key={selectedMeeting.id}
            meeting={selectedMeeting}
            meetings={meetings}
            extractLoading={extractLoading}
            onExtractDone={() => {}}
            onRefreshResolutions={() => {}}
            onSetExtractLoading={setExtractLoading}
            onSelectMeeting={handleSelectMeeting}
            onRetryImport={handleRetryImport}
          />
        )}
      </div>

      <Modal title="新建会议" open={newMeetingOpen} onOk={handleCreateMeeting}
        onCancel={() => { setNewMeetingOpen(false); meetingForm.resetFields() }} okText="创建" cancelText="取消">
        <Form form={meetingForm} layout="vertical">
          <Form.Item name="title" label="会议标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="例如：第X次设计审查会" />
          </Form.Item>
          <Form.Item name="date" label="会议日期" rules={[{ required: true, message: '请选择日期' }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="raw_text" label="纪要文本">
            <Input.TextArea rows={6} placeholder="粘贴或输入会议纪要原文" />
          </Form.Item>
        </Form>
      </Modal>

      {selectedProjectId && (
        <ImportMeetingModal
          open={importOpen}
          onClose={() => setImportOpen(false)}
          projectId={selectedProjectId}
          onImported={handleImported}
        />
      )}
    </div>
  )
}

export default MeetingsView
