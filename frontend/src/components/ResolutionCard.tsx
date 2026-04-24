import { Card, Tag, Button, Tooltip, Popconfirm } from 'antd'
import { EditOutlined, DeleteOutlined, ArrowRightOutlined, ArrowLeftOutlined } from '@ant-design/icons'

// ============ 类型定义 ============

export interface Resolution {
  id: string
  meeting_id: string
  project_id: string
  content: string
  index: number
  status: 'active' | 'amended' | 'superseded'
  source_doc_id: string | null
  created_at: string
}

export interface RelationItem {
  from_id: string
  to_id: string
  relation_type: string
  direction: 'incoming' | 'outgoing'
  from_content?: string
  from_meeting_id?: string
  to_content?: string
  to_meeting_id?: string
}

export const statusConfig: Record<string, { color: string; label: string; emoji: string }> = {
  active: { color: 'green', label: '生效中', emoji: '🟢' },
  amended: { color: 'orange', label: '已修订', emoji: '🟡' },
  superseded: { color: 'red', label: '已替代', emoji: '🔴' },
}

export const relationTypeLabels: Record<string, { color: string; label: string; verb: string; passiveVerb: string }> = {
  SUPERSEDES: { color: 'red', label: '替代', verb: '替代了', passiveVerb: '被…替代' },
  AMENDS: { color: 'orange', label: '修订', verb: '修订了', passiveVerb: '被…修订' },
  SUPPLEMENTS: { color: 'blue', label: '补充', verb: '补充了', passiveVerb: '被…补充' },
}

interface Props {
  resolution: Resolution
  chains: RelationItem[]
  isHighlighted: boolean
  onEdit: (resolution: Resolution) => void
  onDelete: (id: string) => void
  onDeleteRelation: (fromId: string, toId: string, relationType: string) => void
  onJumpToResolution: (id: string) => void
}

export default function ResolutionCard({
  resolution, chains, isHighlighted,
  onEdit, onDelete, onDeleteRelation, onJumpToResolution,
}: Props) {
  const st = statusConfig[resolution.status] || statusConfig.active

  return (
    <Card
      id={`resolution-${resolution.id}`}
      className={`resolution-card resolution-card-${resolution.status} ${isHighlighted ? 'resolution-highlight' : ''}`}
      size="small"
    >
      <div className="resolution-header">
        <span className="resolution-index">决议 {resolution.index}</span>
        <div className="resolution-actions">
          <Tooltip title="编辑">
            <Button type="text" size="small" icon={<EditOutlined />} onClick={() => onEdit(resolution)} />
          </Tooltip>
          <Popconfirm title="确定删除此决议？" onConfirm={() => onDelete(resolution.id)}>
            <Tooltip title="删除">
              <Button type="text" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
          <Tag color={st.color}>{st.emoji} {st.label}</Tag>
        </div>
      </div>
      <p className="resolution-content">{resolution.content}</p>

      {chains.length > 0 && (
        <div className="resolution-relations">
          {chains.map((rel, idx) => {
            const relInfo = relationTypeLabels[rel.relation_type] || {
              color: 'default', label: rel.relation_type,
              verb: rel.relation_type, passiveVerb: rel.relation_type,
            }
            const isOutgoing = rel.from_id === resolution.id
            const targetId = isOutgoing ? rel.to_id : rel.from_id
            const targetContent = isOutgoing ? rel.to_content : rel.from_content
            const summary = targetContent
              ? targetContent.length > 60 ? targetContent.slice(0, 60) + '...' : targetContent
              : '（点击查看）'
            const directionLabel = isOutgoing ? relInfo.verb : relInfo.passiveVerb

            return (
              <div key={idx} className="relation-item">
                <span style={{ cursor: 'pointer', flex: 1 }} onClick={() => onJumpToResolution(targetId)}>
                  {isOutgoing
                    ? <ArrowRightOutlined className="relation-icon" />
                    : <ArrowLeftOutlined className="relation-icon" />
                  }
                  <span>
                    <span className="relation-direction">{directionLabel}</span>
                    <Tag color={relInfo.color} style={{ fontSize: 11, margin: '0 2px' }}>{relInfo.label}</Tag>
                    <span className="relation-summary">{summary}</span>
                  </span>
                </span>
                <Tooltip title="删除关联">
                  <Button
                    type="text" size="small" danger icon={<DeleteOutlined />}
                    onClick={(e) => { e.stopPropagation(); onDeleteRelation(rel.from_id, rel.to_id, rel.relation_type) }}
                  />
                </Tooltip>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
