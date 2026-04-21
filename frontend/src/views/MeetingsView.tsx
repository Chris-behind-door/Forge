/**
 * MeetingsView - 会议纪要管理界面
 *
 * 功能：
 * - 左侧项目选择 + 会议时间线
 * - 右侧会议详情面板（决议卡片、关联链、原始纪要）
 * - 新建会议、添加决议
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Card, Timeline, Tag, Button, Modal, Form, Input, Empty,
  Select, DatePicker, Collapse, message, Spin, Tooltip,
} from 'antd'
import {
  PlusOutlined, CalendarOutlined, LinkOutlined, FileTextOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { getApiBase } from '../api'
import { useProjects } from '../hooks/useProjects'
import './MeetingsView.css'

// ============ 类型定义 ============

interface Meeting {
  id: string
  project_id: string
  title: string
  date: string
  summary: string
  source_doc_id: string | null
  raw_text: string
  created_at: string
}

interface Resolution {
  id: string
  meeting_id: string
  project_id: string
  content: string
  index: number
  status: 'active' | 'amended' | 'superseded'
  source_doc_id: string | null
  created_at: string
}

interface RelationItem {
  from_id: string
  to_id: string
  relation_type: string
  direction: 'incoming' | 'outgoing'
  from_content?: string
  from_meeting_id?: string
  to_content?: string
  to_meeting_id?: string
}

// ============ 样式配置 ============

const statusConfig: Record<string, { color: string; label: string; emoji: string }> = {
  active: { color: 'green', label: '生效中', emoji: '🟢' },
  amended: { color: 'orange', label: '已修订', emoji: '🟡' },
  superseded: { color: 'red', label: '已替代', emoji: '🔴' },
}

const relationTypeLabels: Record<string, { color: string; label: string }> = {
  SUPERSEDES: { color: 'red', label: '替代' },
  AMENDS: { color: 'orange', label: '修订' },
  SUPPLEMENTS: { color: 'blue', label: '补充' },
}

// ============ 主组件 ============

function MeetingsView() {
  const { projects } = useProjects()
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [meetings, setMeetings] = useState<Meeting[]>([])
  const [selectedMeeting, setSelectedMeeting] = useState<Meeting | null>(null)
  const [resolutions, setResolutions] = useState<Resolution[]>([])
  const [relationMap, setRelationMap] = useState<Record<string, RelationItem[]>>({})
  const [meetingsLoading, setMeetingsLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)

  // Modal states
  const [newMeetingOpen, setNewMeetingOpen] = useState(false)
  const [newResolutionOpen, setNewResolutionOpen] = useState(false)
  const [meetingForm] = Form.useForm()
  const [resolutionForm] = Form.useForm()

  // Highlighted resolution (for jump-to)
  const [highlightedResId, setHighlightedResId] = useState<string | null>(null)

  // -------- 数据获取 --------

  const fetchMeetings = useCallback(async (projectId: string) => {
    setMeetingsLoading(true)
    try {
      const res = await fetch(`${getApiBase()}/projects/${projectId}/meetings`)
      if (res.ok) {
        const data = await res.json()
        setMeetings(data.sort((a: Meeting, b: Meeting) => a.date.localeCompare(b.date)))
      }
    } catch { /* ignore */ }
    setMeetingsLoading(false)
  }, [])

  const fetchResolutions = useCallback(async (meetingId: string) => {
    setDetailLoading(true)
    try {
      const res = await fetch(`${getApiBase()}/meetings/${meetingId}/resolutions`)
      if (res.ok) {
        const data = await res.json()
        setResolutions(data.sort((a: Resolution, b: Resolution) => a.index - b.index))

        // Fetch chains for each resolution
        const chains: Record<string, RelationItem[]> = {}
        for (const r of data) {
          try {
            const cr = await fetch(`${getApiBase()}/resolutions/${r.id}/chain`)
            if (cr.ok) {
              const chainData = await cr.json()
              chains[r.id] = chainData.chain || []
            }
          } catch { /* ignore */ }
        }
        setRelationMap(chains)
      }
    } catch { /* ignore */ }
    setDetailLoading(false)
  }, [])

  // 项目切换
  useEffect(() => {
    if (selectedProjectId) {
      fetchMeetings(selectedProjectId)
      setSelectedMeeting(null)
      setResolutions([])
      setRelationMap({})
    } else {
      setMeetings([])
      setSelectedMeeting(null)
    }
  }, [selectedProjectId, fetchMeetings])

  // 会议选择
  const handleSelectMeeting = useCallback((meeting: Meeting) => {
    setSelectedMeeting(meeting)
    fetchResolutions(meeting.id)
    setHighlightedResId(null)
  }, [fetchResolutions])

  // -------- 新建会议 --------

  const handleCreateMeeting = async () => {
    try {
      const values = await meetingForm.validateFields()
      if (!selectedProjectId) return

      const res = await fetch(`${getApiBase()}/projects/${selectedProjectId}/meetings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: values.title,
          date: values.date?.format('YYYY-MM-DD') || dayjs().format('YYYY-MM-DD'),
          raw_text: values.raw_text || '',
        }),
      })

      if (res.ok) {
        message.success('会议已创建')
        setNewMeetingOpen(false)
        meetingForm.resetFields()
        fetchMeetings(selectedProjectId)
      }
    } catch { /* validation */ }
  }

  // -------- 添加决议 --------

  const handleCreateResolution = async () => {
    try {
      const values = await resolutionForm.validateFields()
      if (!selectedMeeting) return

      const res = await fetch(`${getApiBase()}/meetings/${selectedMeeting.id}/resolutions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: values.content,
          status: 'active',
        }),
      })

      if (res.ok) {
        message.success('决议已添加')
        setNewResolutionOpen(false)
        resolutionForm.resetFields()
        fetchResolutions(selectedMeeting.id)
      }
    } catch { /* validation */ }
  }

  // -------- 跳转到关联决议 --------

  const handleJumpToResolution = async (resId: string) => {
    // Check if the resolution belongs to the current meeting
    const inCurrentMeeting = resolutions.some(r => r.id === resId)
    if (!inCurrentMeeting) {
      // Find which meeting this resolution belongs to
      // Search across all meetings in current project
      for (const mtg of meetings) {
        try {
          const res = await fetch(`${getApiBase()}/meetings/${mtg.id}/resolutions`)
          if (res.ok) {
            const mtgResolutions: Resolution[] = await res.json()
            if (mtgResolutions.some(r => r.id === resId)) {
              // Switch to this meeting first
              setSelectedMeeting(mtg)
              setResolutions(mtgResolutions)
              break
            }
          }
        } catch { /* ignore */ }
      }
    }
    setHighlightedResId(resId)
    setTimeout(() => {
      const el = document.getElementById(`resolution-${resId}`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        setTimeout(() => setHighlightedResId(null), 2000)
      }
    }, 300)
  }

  // -------- 渲染 --------

  // Resolve meeting title for a resolution (from relation chain data)
  const getMeetingTitle = (mtgId: string): string => {
    const mtg = meetings.find(m => m.id === mtgId)
    return mtg?.title || '未知会议'
  }

  return (
    <div className="meetings-view">
      {/* 左侧面板 */}
      <div className="meetings-sidebar">
        <div className="sidebar-section">
          <div className="sidebar-section-header">
            <span>项目</span>
          </div>
          <Select
            style={{ width: '100%' }}
            placeholder="选择项目"
            value={selectedProjectId}
            onChange={setSelectedProjectId}
            options={projects.map(p => ({ label: p.name, value: p.id }))}
          />
        </div>

        <div className="sidebar-section">
          <div className="sidebar-section-header">
            <span>会议时间线</span>
            {selectedProjectId && (
              <Button
                type="link"
                size="small"
                icon={<PlusOutlined />}
                onClick={() => setNewMeetingOpen(true)}
              >
                新建
              </Button>
            )}
          </div>
          <Spin spinning={meetingsLoading}>
            {meetings.length === 0 ? (
              <Empty
                description={selectedProjectId ? '暂无会议' : '请先选择项目'}
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            ) : (
              <Timeline
                className="meeting-timeline"
                items={meetings.map(mtg => ({
                  color: selectedMeeting?.id === mtg.id ? 'blue' : 'gray',
                  children: (
                    <div
                      className={`timeline-item ${selectedMeeting?.id === mtg.id ? 'active' : ''}`}
                      onClick={() => handleSelectMeeting(mtg)}
                    >
                      <div className="timeline-item-date">{mtg.date}</div>
                      <div className="timeline-item-title">{mtg.title}</div>
                    </div>
                  ),
                }))}
              />
            )}
          </Spin>
        </div>
      </div>

      {/* 右侧详情 */}
      <div className="meetings-detail">
        {!selectedMeeting ? (
          <Empty description="请从左侧选择一场会议" className="detail-empty" />
        ) : (
          <Spin spinning={detailLoading}>
            {/* 会议标题 */}
            <Card className="meeting-header-card" size="small">
              <div className="meeting-header">
                <div>
                  <h2 className="meeting-title">
                    <CalendarOutlined /> {selectedMeeting.title}
                  </h2>
                  <div className="meeting-meta">
                    <Tag color="blue">{selectedMeeting.date}</Tag>
                    {selectedMeeting.source_doc_id && (
                      <Tag icon={<FileTextOutlined />}>关联文档</Tag>
                    )}
                  </div>
                </div>
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={() => {
                    resolutionForm.resetFields()
                    resolutionForm.resetFields()
                    setNewResolutionOpen(true)
                  }}
                >
                  添加决议
                </Button>
              </div>
            </Card>

            {/* 决议列表 */}
            <div className="resolutions-section">
              <h3 className="section-title">会议决议 ({resolutions.length})</h3>
              {resolutions.length === 0 ? (
                <Empty description="暂无决议" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                resolutions.map(res => {
                  const st = statusConfig[res.status] || statusConfig.active
                  const chains = relationMap[res.id] || []
                  const isHighlighted = highlightedResId === res.id

                  return (
                    <Card
                      key={res.id}
                      id={`resolution-${res.id}`}
                      className={`resolution-card resolution-card-${res.status} ${isHighlighted ? 'resolution-highlight' : ''}`}
                      size="small"
                    >
                      <div className="resolution-header">
                        <span className="resolution-index">决议 {res.index}</span>
                        <Tag color={st.color}>{st.emoji} {st.label}</Tag>
                        {/* 已替代：快速跳转到替代决议 */}
                        {res.status === 'superseded' && chains.some(c => c.from_id !== res.id && c.relation_type === 'SUPERSEDES') && (
                          <Tooltip title="点击跳转到替代决议">
                            <Button
                              type="link"
                              size="small"
                              onClick={() => {
                                const superRel = chains.find(c => c.from_id !== res.id && c.relation_type === 'SUPERSEDES')
                                if (superRel) handleJumpToResolution(superRel.from_id)
                              }}
                            >
                              查看替代决议 →
                            </Button>
                          </Tooltip>
                        )}
                      </div>
                      <p className="resolution-content">{res.content}</p>

                      {/* 关联链 */}
                      {chains.length > 0 && (
                        <div className="resolution-relations">
                          {chains.map((rel, idx) => {
                            const relInfo = relationTypeLabels[rel.relation_type] || { color: 'default', label: rel.relation_type }
                            const isOutgoing = rel.from_id === res.id
                            const targetId = isOutgoing ? rel.to_id : rel.from_id
                            const targetContent = isOutgoing ? rel.to_content : rel.from_content
                            const summary = targetContent
                              ? targetContent.length > 60 ? targetContent.slice(0, 60) + '...' : targetContent
                              : '（点击查看）'

                            return (
                              <div
                                key={idx}
                                className="relation-item"
                                onClick={() => handleJumpToResolution(targetId)}
                              >
                                <LinkOutlined className="relation-icon" />
                                <span>
                                  → <Tag color={relInfo.color} style={{ fontSize: 11 }}>{relInfo.label}</Tag>
                                  <span className="relation-summary">{summary}</span>
                                </span>
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </Card>
                  )
                })
              )}
            </div>

            {/* 原始纪要 */}
            {selectedMeeting.raw_text && (
              <Collapse
                className="raw-text-collapse"
                ghost
                items={[{
                  key: 'raw',
                  label: '原始纪要文本',
                  children: (
                    <pre className="raw-text-content">{selectedMeeting.raw_text}</pre>
                  ),
                }]}
              />
            )}
          </Spin>
        )}
      </div>

      {/* 新建会议 Modal */}
      <Modal
        title="新建会议"
        open={newMeetingOpen}
        onOk={handleCreateMeeting}
        onCancel={() => { setNewMeetingOpen(false); meetingForm.resetFields() }}
        okText="创建"
        cancelText="取消"
      >
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

      {/* 添加决议 Modal */}
      <Modal
        title="添加决议"
        open={newResolutionOpen}
        onOk={handleCreateResolution}
        onCancel={() => { setNewResolutionOpen(false); resolutionForm.resetFields() }}
        okText="添加"
        cancelText="取消"
      >
        <Form form={resolutionForm} layout="vertical">
          <Form.Item name="content" label="决议内容" rules={[{ required: true, message: '请输入决议内容' }]}>
            <Input.TextArea rows={4} placeholder="输入决议内容" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default MeetingsView
