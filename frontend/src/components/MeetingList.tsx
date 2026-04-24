import { Timeline, Spin, Empty, Button, Popconfirm, Tag } from 'antd'
import { PlusOutlined, UploadOutlined, DeleteOutlined, ClockCircleOutlined, WarningOutlined, RedoOutlined } from '@ant-design/icons'

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
}

interface Props {
  meetings: Meeting[]
  selectedMeetingId: string | null
  loading: boolean
  hasProject: boolean
  onSelect: (meeting: Meeting) => void
  onDelete: (id: string) => void
  onNewMeeting: () => void
  onImport: () => void
  onRetryImport: (id: string) => void
}

function MeetingStatusBadge({ status }: { status: string }) {
  switch (status) {
    case 'processing':
      return <Tag icon={<Spin size="small" />} color="processing">处理中</Tag>
    case 'queued':
      return <Tag icon={<ClockCircleOutlined />} color="default">等待中</Tag>
    case 'failed':
      return <Tag icon={<WarningOutlined />} color="error">已失败</Tag>
    default:
      return null
  }
}

export default function MeetingList({
  meetings, selectedMeetingId, loading, hasProject,
  onSelect, onDelete, onNewMeeting, onImport, onRetryImport,
}: Props) {
  return (
    <>
      <div className="sidebar-section-header">
        <span>会议时间线</span>
        {hasProject && (
          <div style={{ display: 'flex', gap: 4 }}>
            <Button type="link" size="small" icon={<PlusOutlined />} onClick={onNewMeeting}>新建</Button>
            <Button type="link" size="small" icon={<UploadOutlined />} onClick={onImport}>导入</Button>
          </div>
        )}
      </div>
      <Spin spinning={loading}>
        {meetings.length === 0 ? (
          <Empty description={hasProject ? '暂无会议' : '请先选择项目'} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Timeline
            className="meeting-timeline"
            items={meetings.map(mtg => {
              const isActive = mtg.status === 'active' || !mtg.status
              return {
                color: selectedMeetingId === mtg.id ? 'blue' : 'gray',
                content: (
                  <div
                    className={`timeline-item ${selectedMeetingId === mtg.id ? 'active' : ''} ${!isActive ? 'disabled' : ''}`}
                    onClick={() => { if (isActive) onSelect(mtg) }}
                  >
                    <div className="timeline-item-row">
                      <div>
                        <div className="timeline-item-date">{mtg.date}</div>
                        <div className="timeline-item-title">{mtg.title}</div>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }} onClick={(e) => e.stopPropagation()}>
                        {!isActive && <MeetingStatusBadge status={mtg.status!} />}
                        {mtg.status === 'failed' && (
                          <Button type="link" size="small" icon={<RedoOutlined />}
                            onClick={() => onRetryImport(mtg.id)} title="重试导入" />
                        )}
                        <Popconfirm title={`确定删除此会议${isActive ? '及其所有决议' : ''}？`} onConfirm={() => onDelete(mtg.id)}>
                          <Button type="text" size="small" danger icon={<DeleteOutlined />}
                            onClick={(e) => e.stopPropagation()} className="timeline-delete-btn" />
                        </Popconfirm>
                      </div>
                    </div>
                  </div>
                ),
              }
            })}
          />
        )}
      </Spin>
    </>
  )
}
