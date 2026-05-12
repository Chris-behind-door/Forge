import { useState } from 'react'
import { Card, List, Tag, Button, Popconfirm, Empty, Dropdown } from 'antd'
import { FilePdfOutlined, FileTextOutlined, DeleteOutlined, ReloadOutlined, SyncOutlined, SwapOutlined } from '@ant-design/icons'
import { getApiBase } from '../api'
import { message } from 'antd'

interface Document {
  id: string
  name: string
  size: number
  file_type: 'pdf' | 'chm'
  uploaded_at: string
  status: 'pending' | 'processing' | 'ready' | 'error' | 'queued'
  chunk_count: number | null
  project_id: string | null
}

const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const statusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '等待处理' },
  queued: { color: 'warning', text: '排队中' },
  processing: { color: 'processing', text: '处理中...' },
  ready: { color: 'success', text: '已就绪' },
  error: { color: 'error', text: '处理失败' },
}

interface Props {
  documents: Document[]
  projects: { id: string; name: string }[]
  loading: boolean
  onRefresh: () => void
}

export default function DocumentList({ documents, projects, loading, onRefresh }: Props) {
  const [reprocessingAll, setReprocessingAll] = useState(false)

  const handleDelete = async (docId: string) => {
    try {
      const res = await fetch(`${getApiBase()}/documents/${docId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('删除失败')
      message.success('已删除文档'); onRefresh()
    } catch (err) { message.error(`删除失败: ${err}`) }
  }

  const handleReprocess = async (docId: string) => {
    try {
      const res = await fetch(`${getApiBase()}/documents/${docId}/reprocess`, { method: 'POST' })
      if (!res.ok) throw new Error('重新处理失败')
      const data = await res.json()
      message.success(`开始重新处理，已删除 ${data.deleted_chunks} 条旧数据`); onRefresh()
    } catch (err) { message.error(`重新处理失败: ${err}`) }
  }

  const handleReprocessAll = async () => {
    setReprocessingAll(true)
    try {
      const res = await fetch(`${getApiBase()}/documents/reprocess-all`, { method: 'POST' })
      if (!res.ok) throw new Error('重新处理失败')
      const data = await res.json()
      message.success(`开始重新处理 ${data.total} 个文档`); onRefresh()
    } catch (err) { message.error(`重新处理失败: ${err}`) }
    finally { setReprocessingAll(false) }
  }

  const handleMoveDocument = async (docId: string, targetProjectId: string | null) => {
    try {
      const res = await fetch(`${getApiBase()}/documents/${docId}/move`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: targetProjectId }),
      })
      if (!res.ok) throw new Error('移动失败')
      message.success('文档已移动'); onRefresh()
    } catch (err) { message.error(`移动失败: ${err}`) }
  }

  const moveMenuItems = [
    { key: '__general__', label: '通用知识' },
    ...projects.map(p => ({ key: p.id, label: p.name })),
  ]

  return (
    <Card className="document-list-card" title={`已上传文档 (${documents.length})`}
      extra={documents.length > 0 && (
        <Popconfirm title="重新处理全部文档？" description="将删除所有向量数据并重新解析"
          onConfirm={handleReprocessAll} okText="确定" cancelText="取消">
          <Button type="text" icon={<SyncOutlined />} loading={reprocessingAll} size="small">重建索引</Button>
        </Popconfirm>
      )}
      loading={loading}
    >
      {documents.length === 0 ? (
        <Empty description="暂无文档，请上传 PDF 或 CHM 文件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List dataSource={documents} renderItem={(doc) => (
          <List.Item
            actions={[
              <Dropdown key="move" menu={{
                items: moveMenuItems.map(item => ({
                  key: item.key, label: item.label,
                  disabled: (item.key === '__general__' ? null : item.key) === doc.project_id,
                })),
                onClick: ({ key }) => handleMoveDocument(doc.id, key === '__general__' ? null : key),
              }}>
                <Button type="text" icon={<SwapOutlined />} size="small" title="移动到其他项目" />
              </Dropdown>,
              (doc.status === 'ready' || doc.status === 'error') && (
                <Button key="reprocess" type="text" icon={<ReloadOutlined />} size="small" title="重新处理"
                  onClick={() => handleReprocess(doc.id)} />
              ),
              <Popconfirm key="delete" title="确认删除此文档？" description="删除后无法恢复"
                onConfirm={() => handleDelete(doc.id)} okText="删除" cancelText="取消">
                <Button type="text" danger icon={<DeleteOutlined />} size="small" />
              </Popconfirm>,
            ].filter(Boolean)}
          >
            <List.Item.Meta
              avatar={doc.file_type === 'chm'
                ? <FileTextOutlined className="doc-icon" style={{ color: '#1890ff' }} />
                : <FilePdfOutlined className="doc-icon" style={{ color: '#f5222d' }} />}
              title={doc.name}
              description={
                <>
                  <Tag style={{ marginRight: 4 }}>{doc.file_type.toUpperCase()}</Tag>
                  {formatFileSize(doc.size)}
                  {doc.chunk_count !== null && doc.chunk_count > 0 && <span> · {doc.chunk_count} 个片段</span>}
                  <span> · {new Date(doc.uploaded_at).toLocaleString()}</span>
                </>
              }
            />
            <Tag color={statusConfig[doc.status]?.color || 'default'}>
              {statusConfig[doc.status]?.text || doc.status}
            </Tag>
          </List.Item>
        )} />
      )}
    </Card>
  )
}
