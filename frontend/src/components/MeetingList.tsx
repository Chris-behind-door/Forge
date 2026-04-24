import { Timeline, Spin, Empty, Button, Popconfirm } from 'antd'
import { PlusOutlined, UploadOutlined, DeleteOutlined } from '@ant-design/icons'

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
  meetings: Meeting[]
  selectedMeetingId: string | null
  loading: boolean
  hasProject: boolean
  onSelect: (meeting: Meeting) => void
  onDelete: (id: string) => void
  onNewMeeting: () => void
  onImport: () => void
}

export default function MeetingList({
  meetings, selectedMeetingId, loading, hasProject,
  onSelect, onDelete, onNewMeeting, onImport,
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
            items={meetings.map(mtg => ({
              color: selectedMeetingId === mtg.id ? 'blue' : 'gray',
              content: (
                <div
                  className={`timeline-item ${selectedMeetingId === mtg.id ? 'active' : ''}`}
                  onClick={() => onSelect(mtg)}
                >
                  <div className="timeline-item-row">
                    <div>
                      <div className="timeline-item-date">{mtg.date}</div>
                      <div className="timeline-item-title">{mtg.title}</div>
                    </div>
                    <span onClick={(e) => e.stopPropagation()}>
                    <Popconfirm title="确定删除此会议及其所有决议？" onConfirm={() => onDelete(mtg.id)}>
                      <Button type="text" size="small" danger icon={<DeleteOutlined />}
                        onClick={(e) => e.stopPropagation()} className="timeline-delete-btn" />
                    </Popconfirm>
                    </span>
                  </div>
                </div>
              ),
            }))}
          />
        )}
      </Spin>
    </>
  )
}
