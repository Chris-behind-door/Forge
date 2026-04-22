/**
 * MeetingsView - 会议纪要管理界面
 *
 * 功能：
 * - 左侧项目选择 + 会议时间线
 * - 右侧会议详情面板（决议卡片、关联链、原始纪要）
 * - 新建会议、导入文件、AI 提取决议
 * - 决议增删改、关联链跳转
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Card, Timeline, Tag, Button, Modal, Form, Input, Empty,
  Select, DatePicker, Collapse, message, Spin, Tooltip,
  Upload, Popconfirm, Alert,
} from 'antd'
import {
  PlusOutlined, CalendarOutlined, FileTextOutlined,
  UploadOutlined, RobotOutlined, CheckCircleOutlined,
  DeleteOutlined, EditOutlined, ArrowRightOutlined, ArrowLeftOutlined,
  LoadingOutlined,
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

const relationTypeLabels: Record<string, { color: string; label: string; verb: string; passiveVerb: string }> = {
  SUPERSEDES: { color: 'red', label: '替代', verb: '替代了', passiveVerb: '被…替代' },
  AMENDS: { color: 'orange', label: '修订', verb: '修订了', passiveVerb: '被…修订' },
  SUPPLEMENTS: { color: 'blue', label: '补充', verb: '补充了', passiveVerb: '被…补充' },
}

const LONG_OP_HINT = '处理可能需要几分钟，请耐心等待。'

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
  const [importOpen, setImportOpen] = useState(false)
  const [importLoading, setImportLoading] = useState(false)
  const [extractLoading, setExtractLoading] = useState(false)
  const [extractResult, setExtractResult] = useState<{
    meeting: Meeting
    resolutions: Resolution[]
    relations: any[]
    message: string
  } | null>(null)
  const [meetingForm] = Form.useForm()
  const [resolutionForm] = Form.useForm()
  const [importForm] = Form.useForm()

  // Edit resolution modal
  const [editResolutionOpen, setEditResolutionOpen] = useState(false)
  const [editingResolution, setEditingResolution] = useState<Resolution | null>(null)
  const [editForm] = Form.useForm()

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
        const promises = data.map(async (r: Resolution) => {
          try {
            const cr = await fetch(`${getApiBase()}/resolutions/${r.id}/chain`)
            if (cr.ok) {
              const chainData = await cr.json()
              chains[r.id] = chainData.chain || []
            }
          } catch { /* ignore */ }
        })
        await Promise.all(promises)
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

  // -------- 编辑决议 --------

  const handleEditResolution = (resolution: Resolution) => {
    setEditingResolution(resolution)
    editForm.setFieldsValue({
      content: resolution.content,
      status: resolution.status,
    })
    setEditResolutionOpen(true)
  }

  const handleSaveEditResolution = async () => {
    try {
      const values = await editForm.validateFields()
      if (!editingResolution) return

      const res = await fetch(`${getApiBase()}/resolutions/${editingResolution.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      })

      if (res.ok) {
        message.success('决议已更新')
        setEditResolutionOpen(false)
        setEditingResolution(null)
        if (selectedMeeting) {
          fetchResolutions(selectedMeeting.id)
        }
      } else {
        message.error('更新失败')
      }
    } catch { /* validation */ }
  }

  // -------- 删除决议 --------

  const handleDeleteResolution = async (resId: string) => {
    try {
      const res = await fetch(`${getApiBase()}/resolutions/${resId}`, {
        method: 'DELETE',
      })
      if (res.ok) {
        message.success('决议已删除')
        if (selectedMeeting) {
          fetchResolutions(selectedMeeting.id)
        }
      } else {
        message.error('删除失败')
      }
    } catch {
      message.error('删除失败')
    }
  }

  // -------- 删除会议 --------

  const handleDeleteMeeting = async (meetingId: string) => {
    try {
      const res = await fetch(`${getApiBase()}/meetings/${meetingId}`, {
        method: 'DELETE',
      })
      if (res.ok) {
        message.success('会议已删除')
        if (selectedMeeting?.id === meetingId) {
          setSelectedMeeting(null)
          setResolutions([])
          setRelationMap({})
        }
        if (selectedProjectId) {
          fetchMeetings(selectedProjectId)
        }
      } else {
        message.error('删除失败')
      }
    } catch {
      message.error('删除失败')
    }
  }

  // -------- AI 提取决议 --------

  const handleExtract = async () => {
    if (!selectedMeeting) return
    setExtractLoading(true)
    try {
      const res = await fetch(`${getApiBase()}/meetings/${selectedMeeting.id}/extract`, {
        method: 'POST',
      })
      if (res.ok) {
        const data = await res.json()
        message.success(data.message || `提取了 ${data.resolutions?.length || 0} 条决议`)
        fetchResolutions(selectedMeeting.id)
      } else {
        const err = await res.json()
        message.error(err.detail || '提取失败')
      }
    } catch {
      message.error('请求失败，请检查网络')
    }
    setExtractLoading(false)
  }

  // -------- 跳转到关联决议 --------

  const handleJumpToResolution = async (resId: string) => {
    const inCurrentMeeting = resolutions.some(r => r.id === resId)
    if (!inCurrentMeeting) {
      for (const mtg of meetings) {
        try {
          const res = await fetch(`${getApiBase()}/meetings/${mtg.id}/resolutions`)
          if (res.ok) {
            const mtgResolutions: Resolution[] = await res.json()
            if (mtgResolutions.some(r => r.id === resId)) {
              setSelectedMeeting(mtg)
              setResolutions(mtgResolutions)
              const chains: Record<string, RelationItem[]> = {}
              const promises = mtgResolutions.map(async (r: Resolution) => {
                try {
                  const cr = await fetch(`${getApiBase()}/resolutions/${r.id}/chain`)
                  if (cr.ok) {
                    const chainData = await cr.json()
                    chains[r.id] = chainData.chain || []
                  }
                } catch { /* ignore */ }
              })
              await Promise.all(promises)
              setRelationMap(chains)
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
              <div style={{ display: 'flex', gap: 4 }}>
                <Button
                  type="link"
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={() => setNewMeetingOpen(true)}
                >
                  新建
                </Button>
                <Button
                  type="link"
                  size="small"
                  icon={<UploadOutlined />}
                  onClick={() => { importForm.resetFields(); setExtractResult(null); setImportOpen(true) }}
                >
                  导入
                </Button>
              </div>
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
                      <div className="timeline-item-row">
                        <div>
                          <div className="timeline-item-date">{mtg.date}</div>
                          <div className="timeline-item-title">{mtg.title}</div>
                        </div>
                        <Popconfirm
                          title="确定删除此会议及其所有决议？"
                          onConfirm={() => handleDeleteMeeting(mtg.id)}
                        >
                          <Button
                            type="text"
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={(e) => e.stopPropagation()}
                            className="timeline-delete-btn"
                          />
                        </Popconfirm>
                      </div>
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
                <div style={{ flex: 1 }}>
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
                <div className="meeting-actions">
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    onClick={() => {
                      resolutionForm.resetFields()
                      setNewResolutionOpen(true)
                    }}
                  >
                    添加决议
                  </Button>
                  <Button
                    icon={extractLoading ? <LoadingOutlined /> : <RobotOutlined />}
                    onClick={handleExtract}
                    disabled={extractLoading}
                  >
                    AI 提取决议
                  </Button>
                </div>
              </div>
              {extractLoading && (
                <Alert
                  type="info"
                  showIcon
                  message="正在分析会议纪要并提取决议..."
                  description="处理可能需要几分钟，请耐心等待。"
                  style={{ marginTop: 12 }}
                />
              )}
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
                        <div className="resolution-actions">
                          <Tooltip title="编辑">
                            <Button
                              type="text"
                              size="small"
                              icon={<EditOutlined />}
                              onClick={() => handleEditResolution(res)}
                            />
                          </Tooltip>
                          <Popconfirm
                            title="确定删除此决议？"
                            onConfirm={() => handleDeleteResolution(res.id)}
                          >
                            <Tooltip title="删除">
                              <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                            </Tooltip>
                          </Popconfirm>
                          <Tag color={st.color}>{st.emoji} {st.label}</Tag>
                        </div>
                      </div>
                      <p className="resolution-content">{res.content}</p>

                      {/* 关联链 */}
                      {chains.length > 0 && (
                        <div className="resolution-relations">
                          {chains.map((rel, idx) => {
                            const relInfo = relationTypeLabels[rel.relation_type] || {
                              color: 'default', label: rel.relation_type,
                              verb: rel.relation_type, passiveVerb: rel.relation_type,
                            }
                            const isOutgoing = rel.from_id === res.id
                            const targetId = isOutgoing ? rel.to_id : rel.from_id
                            const targetContent = isOutgoing ? rel.to_content : rel.from_content
                            const summary = targetContent
                              ? targetContent.length > 60 ? targetContent.slice(0, 60) + '...' : targetContent
                              : '（点击查看）'
                            const directionLabel = isOutgoing
                              ? `${relInfo.verb}`
                              : `${relInfo.passiveVerb}`

                            return (
                              <div
                                key={idx}
                                className="relation-item"
                                onClick={() => handleJumpToResolution(targetId)}
                              >
                                {isOutgoing
                                  ? <ArrowRightOutlined className="relation-icon" />
                                  : <ArrowLeftOutlined className="relation-icon" />
                                }
                                <span>
                                  <span className="relation-direction">{directionLabel}</span>
                                  <Tag color={relInfo.color} style={{ fontSize: 11, margin: '0 2px' }}>{relInfo.label}</Tag>
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

      {/* 编辑决议 Modal */}
      <Modal
        title="编辑决议"
        open={editResolutionOpen}
        onOk={handleSaveEditResolution}
        onCancel={() => { setEditResolutionOpen(false); setEditingResolution(null); editForm.resetFields() }}
        okText="保存"
        cancelText="取消"
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="content" label="决议内容" rules={[{ required: true, message: '请输入决议内容' }]}>
            <Input.TextArea rows={4} placeholder="输入决议内容" />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select
              options={Object.entries(statusConfig).map(([k, v]) => ({
                value: k, label: `${v.emoji} ${v.label}`,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 导入纪要 Modal */}
      <Modal
        title="导入会议纪要"
        open={importOpen}
        onCancel={() => { setImportOpen(false); setExtractResult(null); importForm.resetFields(); setImportLoading(false) }}
        footer={extractResult ? [
          <Button key="close" onClick={() => { setImportOpen(false); setExtractResult(null); importForm.resetFields() }}>
            关闭
          </Button>,
        ] : undefined}
        okText={importLoading ? '处理中...' : '导入并提取'}
        onOk={() => importForm.submit()}
        confirmLoading={importLoading}
        okButtonProps={{ disabled: importLoading }}
        cancelButtonProps={{ disabled: importLoading }}
        width={720}
      >
        {extractResult ? (
          <div>
            <div style={{ marginBottom: 12, padding: '8px 12px', background: '#f6ffed', borderRadius: 6, border: '1px solid #b7eb8f' }}>
              <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
              {extractResult.message}
            </div>
            {extractResult.resolutions.length > 0 && (
              <div>
                <h4 style={{ margin: '12px 0 8px' }}>提取的决议：</h4>
                {extractResult.resolutions.map((r: any, idx: number) => (
                  <Card key={r.id || idx} size="small" style={{ marginBottom: 8, borderLeft: '3px solid #52c41a' }}>
                    <div style={{ fontWeight: 600, marginBottom: 4 }}>决议 {r.index}</div>
                    <div style={{ color: '#444', fontSize: 13 }}>{r.content}</div>
                  </Card>
                ))}
              </div>
            )}
            {extractResult.relations.length > 0 && (
              <div>
                <h4 style={{ margin: '12px 0 8px' }}>检测到的关联：</h4>
                {extractResult.relations.map((rel: any, idx: number) => (
                  <div key={idx} style={{ marginBottom: 6, fontSize: 13, color: '#555' }}>
                    <Tag color={rel.type === 'SUPERSEDES' ? 'red' : rel.type === 'AMENDS' ? 'orange' : 'blue'}>
                      {rel.type === 'SUPERSEDES' ? '替代' : rel.type === 'AMENDS' ? '修订' : '补充'}
                    </Tag>
                    <span>{rel.reason}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div>
            <Alert
              type="info"
              showIcon
              message="上传文件后将自动提取决议并建立跨会议关联"
              description={LONG_OP_HINT}
              style={{ marginBottom: 16 }}
            />
            <Form form={importForm} layout="vertical" onFinish={async (values) => {
              if (!selectedProjectId || !values.file?.[0]) return
              setImportLoading(true)
              try {
                const formData = new FormData()
                formData.append('file', values.file[0])
                formData.append('date', values.date?.format('YYYY-MM-DD') || '')
                formData.append('title', values.title || '')
                const res = await fetch(`${getApiBase()}/projects/${selectedProjectId}/meetings/import`, {
                  method: 'POST',
                  body: formData,
                })
                if (res.ok) {
                  const data = await res.json()
                  setExtractResult(data)
                  fetchMeetings(selectedProjectId)
                } else {
                  const err = await res.json()
                  message.error(err.detail || '导入失败')
                }
              } catch {
                message.error('导入失败')
              }
              setImportLoading(false)
            }}>
              <Form.Item name="file" label="纪要文件" rules={[{ required: true, message: '请选择文件' }]}>
                <Upload beforeUpload={() => false} maxCount={1} accept=".pdf,.txt,.md,.doc,.docx">
                  <Button icon={<UploadOutlined />}>选择文件</Button>
                </Upload>
              </Form.Item>
              <Form.Item name="date" label="会议日期" rules={[{ required: true, message: '请选择日期' }]}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="title" label="会议标题（可选）">
                <Input placeholder="留空则使用文件名" />
              </Form.Item>
            </Form>
          </div>
        )}
      </Modal>
    </div>
  )
}

export default MeetingsView
