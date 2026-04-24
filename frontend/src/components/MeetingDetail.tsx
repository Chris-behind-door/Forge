import { useState, useCallback } from 'react'
import { Card, Button, Modal, Form, Input, Select, Spin, Empty, Collapse, Alert, Tag, message } from 'antd'
import {
  PlusOutlined, CalendarOutlined, FileTextOutlined,
  RobotOutlined, LoadingOutlined,
} from '@ant-design/icons'
import { getApiBase } from '../api'
import ResolutionCard, { statusConfig, type Resolution, type RelationItem } from './ResolutionCard'

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

interface Props {
  meeting: Meeting
  meetings: Meeting[]
  extractLoading: boolean
  onExtractDone: () => void
  onRefreshResolutions: () => void
  onSetExtractLoading: (v: boolean) => void
  onSelectMeeting: (m: Meeting) => void
}

export default function MeetingDetail({
  meeting, meetings, extractLoading,
  onExtractDone, onRefreshResolutions, onSetExtractLoading, onSelectMeeting,
}: Props) {
  const [resolutions, setResolutions] = useState<Resolution[]>([])
  const [relationMap, setRelationMap] = useState<Record<string, RelationItem[]>>({})
  const [detailLoading, setDetailLoading] = useState(false)
  const [highlightedResId, setHighlightedResId] = useState<string | null>(null)
  const [newResolutionOpen, setNewResolutionOpen] = useState(false)
  const [editResolutionOpen, setEditResolutionOpen] = useState(false)
  const [editingResolution, setEditingResolution] = useState<Resolution | null>(null)
  const [reextractConfirmOpen, setReextractConfirmOpen] = useState(false)
  const [resolutionForm] = Form.useForm()
  const [editForm] = Form.useForm()

  // -------- 数据获取 --------

  const fetchResolutions = useCallback(async (meetingId: string) => {
    setDetailLoading(true)
    try {
      const res = await fetch(`${getApiBase()}/meetings/${meetingId}/resolutions`)
      if (res.ok) {
        const data = await res.json()
        setResolutions(data.sort((a: Resolution, b: Resolution) => a.index - b.index))
        const chains: Record<string, RelationItem[]> = {}
        await Promise.all(data.map(async (r: Resolution) => {
          try {
            const cr = await fetch(`${getApiBase()}/resolutions/${r.id}/chain`)
            if (cr.ok) { const chainData = await cr.json(); chains[r.id] = chainData.chain || [] }
          } catch { /* ignore */ }
        }))
        setRelationMap(chains)
      }
    } catch { /* ignore */ }
    setDetailLoading(false)
  }, [])

  // 当 meeting 变化时加载
  const isFirstRender = useState(true)
  if (isFirstRender[0]) {
    isFirstRender[1](false)
    fetchResolutions(meeting.id)
  }

  // -------- Handlers --------

  const handleCreateResolution = async () => {
    try {
      const values = await resolutionForm.validateFields()
      const res = await fetch(`${getApiBase()}/meetings/${meeting.id}/resolutions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: values.content, status: 'active' }),
      })
      if (res.ok) { message.success('决议已添加'); setNewResolutionOpen(false); resolutionForm.resetFields(); fetchResolutions(meeting.id) }
    } catch { /* validation */ }
  }

  const handleEditResolution = (resolution: Resolution) => {
    setEditingResolution(resolution)
    editForm.setFieldsValue({ content: resolution.content, status: resolution.status })
    setEditResolutionOpen(true)
  }

  const handleSaveEditResolution = async () => {
    try {
      const values = await editForm.validateFields()
      if (!editingResolution) return
      const res = await fetch(`${getApiBase()}/resolutions/${editingResolution.id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
      })
      if (res.ok) { message.success('决议已更新'); setEditResolutionOpen(false); setEditingResolution(null); fetchResolutions(meeting.id) }
      else message.error('更新失败')
    } catch { /* validation */ }
  }

  const handleDeleteResolution = async (resId: string) => {
    try {
      const res = await fetch(`${getApiBase()}/resolutions/${resId}`, { method: 'DELETE' })
      if (res.ok) { message.success('决议已删除'); fetchResolutions(meeting.id) }
      else message.error('删除失败')
    } catch { message.error('删除失败') }
  }

  const handleDoExtract = async () => {
    setReextractConfirmOpen(false)
    onSetExtractLoading(true)
    try {
      const res = await fetch(`${getApiBase()}/meetings/${meeting.id}/extract`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        const msg = data.cleared > 0
          ? `已清空 ${data.cleared} 条旧决议，重新提取了 ${data.resolutions?.length || 0} 条决议`
          : `提取了 ${data.resolutions?.length || 0} 条决议`
        message.success(msg)
        fetchResolutions(meeting.id)
      } else { const err = await res.json(); message.error(err.detail || '提取失败') }
    } catch { message.error('请求失败，请检查网络') }
    onSetExtractLoading(false)
  }

  const handleDeleteRelation = async (fromId: string, toId: string, relationType: string) => {
    try {
      const params = new URLSearchParams({ from_id: fromId, to_id: toId, relation_type: relationType })
      const res = await fetch(`${getApiBase()}/relations?${params}`, { method: 'DELETE' })
      if (res.ok) { message.success('关联已删除'); fetchResolutions(meeting.id) }
      else message.error('删除关联失败')
    } catch { message.error('删除关联失败') }
  }

  const handleJumpToResolution = async (resId: string) => {
    const inCurrentMeeting = resolutions.some(r => r.id === resId)
    if (!inCurrentMeeting) {
      for (const mtg of meetings) {
        try {
          const res = await fetch(`${getApiBase()}/meetings/${mtg.id}/resolutions`)
          if (res.ok) {
            const mtgResolutions: Resolution[] = await res.json()
            if (mtgResolutions.some(r => r.id === resId)) {
              onSelectMeeting(mtg)
              break
            }
          }
        } catch { /* ignore */ }
      }
    }
    setHighlightedResId(resId)
    setTimeout(() => {
      const el = document.getElementById(`resolution-${resId}`)
      if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); setTimeout(() => setHighlightedResId(null), 2000) }
    }, 300)
  }

  // -------- Render --------

  return (
    <Spin spinning={detailLoading}>
      <Card className="meeting-header-card" size="small">
        <div className="meeting-header">
          <div style={{ flex: 1 }}>
            <h2 className="meeting-title"><CalendarOutlined /> {meeting.title}</h2>
            <div className="meeting-meta">
              <Tag color="blue">{meeting.date}</Tag>
              {meeting.source_doc_id && <Tag icon={<FileTextOutlined />}>关联文档</Tag>}
            </div>
          </div>
          <div className="meeting-actions">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => { resolutionForm.resetFields(); setNewResolutionOpen(true) }}>
              添加决议
            </Button>
            <Button
              icon={extractLoading ? <LoadingOutlined /> : <RobotOutlined />}
              onClick={() => { resolutions.length > 0 ? setReextractConfirmOpen(true) : handleDoExtract() }}
              disabled={extractLoading}
            >
              {resolutions.length > 0 ? '重新提取' : 'AI 提取决议'}
            </Button>
          </div>
        </div>
        {extractLoading && (
          <Alert type="info" showIcon message="正在分析会议纪要并提取决议..." description="处理可能需要几分钟，请耐心等待。" style={{ marginTop: 12 }} />
        )}
      </Card>

      <div className="resolutions-section">
        <h3 className="section-title">会议决议 ({resolutions.length})</h3>
        {resolutions.length === 0 ? (
          <Empty description="暂无决议" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : resolutions.map(res => (
          <ResolutionCard
            key={res.id} resolution={res}
            chains={relationMap[res.id] || []}
            isHighlighted={highlightedResId === res.id}
            onEdit={handleEditResolution}
            onDelete={handleDeleteResolution}
            onDeleteRelation={handleDeleteRelation}
            onJumpToResolution={handleJumpToResolution}
          />
        ))}
      </div>

      {meeting.raw_text && (
        <Collapse className="raw-text-collapse" ghost items={[{
          key: 'raw', label: '原始纪要文本',
          children: <pre className="raw-text-content">{meeting.raw_text}</pre>,
        }]} />
      )}

      {/* Modals */}
      <Modal title="添加决议" open={newResolutionOpen} onOk={handleCreateResolution}
        onCancel={() => { setNewResolutionOpen(false); resolutionForm.resetFields() }} okText="添加" cancelText="取消">
        <Form form={resolutionForm} layout="vertical">
          <Form.Item name="content" label="决议内容" rules={[{ required: true, message: '请输入决议内容' }]}>
            <Input.TextArea rows={4} placeholder="输入决议内容" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="编辑决议" open={editResolutionOpen} onOk={handleSaveEditResolution}
        onCancel={() => { setEditResolutionOpen(false); setEditingResolution(null); editForm.resetFields() }} okText="保存" cancelText="取消">
        <Form form={editForm} layout="vertical">
          <Form.Item name="content" label="决议内容" rules={[{ required: true, message: '请输入决议内容' }]}>
            <Input.TextArea rows={4} placeholder="输入决议内容" />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={Object.entries(statusConfig).map(([k, v]) => ({ value: k, label: `${v.emoji} ${v.label}` }))} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="重新提取决议" open={reextractConfirmOpen} onOk={handleDoExtract}
        onCancel={() => setReextractConfirmOpen(false)} okText="确认重新提取" cancelText="取消" okButtonProps={{ danger: true }}>
        <p>该会议已有 <strong>{resolutions.length}</strong> 条决议，重新提取将清空并替换，是否继续？</p>
      </Modal>
    </Spin>
  )
}
