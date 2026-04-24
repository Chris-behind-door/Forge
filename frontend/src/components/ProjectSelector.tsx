import { Card, List, Tag, Button, Popconfirm } from 'antd'
import { EditOutlined, DeleteOutlined, PlusOutlined, FolderOutlined } from '@ant-design/icons'

interface Props {
  projects: { id: string; name: string; description?: string }[]
  selectedProjectId: string | null
  onSelect: (id: string | null) => void
  onCreate: () => void
  onEdit: (project: { id: string; name: string; description?: string }) => void
  onDelete: (id: string) => void
}

export default function ProjectSelector({ projects, selectedProjectId, onSelect, onCreate, onEdit, onDelete }: Props) {
  return (
    <Card
      className="project-card"
      title={<><FolderOutlined /> 项目管理</>}
      extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={onCreate}>新建项目</Button>}
    >
      <List
        size="small"
        dataSource={[
          { id: '__general__', name: '通用知识', description: '未归属项目的文档', isSpecial: true as const },
          ...projects.map(p => ({ ...p, isSpecial: false as const })),
        ]}
        renderItem={(item) => {
          const pid = item.isSpecial ? null : item.id
          const isSelected = pid === selectedProjectId
          return (
            <List.Item
              style={{
                background: isSelected ? '#e6f4ff' : undefined,
                border: isSelected ? '1px solid #91caff' : undefined,
                borderRadius: 6, cursor: 'pointer',
              }}
              onClick={() => onSelect(pid)}
              actions={item.isSpecial ? undefined : [
                <Button key="edit" type="text" icon={<EditOutlined />} size="small" onClick={(e) => { e.stopPropagation(); onEdit(item) }} />,
                <Popconfirm key="delete" title="确认删除此项目？" description="项目下的文档将一并删除，无法恢复"
                  onConfirm={(e) => { e?.stopPropagation(); onDelete(item.id) }} okText="删除" cancelText="取消">
                  <Button type="text" danger icon={<DeleteOutlined />} size="small" onClick={(e) => e.stopPropagation()} />
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={item.isSpecial ? <><Tag color="blue">默认</Tag>{item.name}</> : item.name}
                description={item.description}
              />
            </List.Item>
          )
        }}
      />
    </Card>
  )
}
