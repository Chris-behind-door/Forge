/**
 * KnowledgeBaseView - 文档管理界面
 *
 * 功能：
 * - 拖拽/点击上传 PDF 文档
 * - 显示文档列表和处理状态
 * - 处理中时自动轮询更新状态
 *
 * 技术要点：
 * - 使用 Tauri 原生拖拽 API（兼容 Linux/WebKitGTK）
 * - 轮询时静默更新，避免 UI 闪烁
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { Button, Card, List, Tag, message, Popconfirm, Empty } from 'antd'
import {
  UploadOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  DeleteOutlined,
  InboxOutlined,
  ReloadOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import './KnowledgeBaseView.css'

// ============ 类型定义 ============

/** 后端 API 基础地址 */
const API_BASE = 'http://127.0.0.1:8765'

/** 文档数据结构 */
interface Document {
  id: string
  name: string
  size: number
  file_type: 'pdf' | 'chm'  // 文件类型
  uploaded_at: string
  status: 'pending' | 'processing' | 'ready' | 'error'
  chunk_count: number | null
}

/** Tauri 拖拽事件载荷 */
interface DragDropPayload {
  type: 'enter' | 'over' | 'drop' | 'leave' | 'cancel'
  paths?: string[]
  position?: { x: number; y: number }
}

interface DragDropEvent {
  event: string
  payload: DragDropPayload
  id: number
}

// ============ 工具函数 ============

/** 检查是否为支持的文件类型 */
const isSupportedFile = (name: string): boolean => {
  const ext = name.toLowerCase().split('.').pop()
  return ext === 'pdf' || ext === 'chm'
}

/** 格式化文件大小 */
const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** 状态显示配置 */
const statusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '等待处理' },
  processing: { color: 'processing', text: '处理中...' },
  ready: { color: 'success', text: '已就绪' },
  error: { color: 'error', text: '处理失败' },
}

// ============ 主组件 ============

function KnowledgeBaseView() {
  // -------- 状态 --------
  const [documents, setDocuments] = useState<Document[]>([])
  const [initialLoading, setInitialLoading] = useState(true) // 仅首次加载
  const [uploading, setUploading] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [reprocessingAll, setReprocessingAll] = useState(false) // 重新处理全部
  const lastDropTimeRef = useRef<number>(0)

  // -------- 数据获取 --------

  /**
   * 等待后端服务就绪
   * @param maxRetries 最大重试次数
   * @param retryDelay 重试间隔（毫秒）
   */
  const waitForBackend = useCallback(async (maxRetries = 10, retryDelay = 500) => {
    for (let i = 0; i < maxRetries; i++) {
      try {
        const res = await fetch(`${API_BASE}/health`, { 
          signal: AbortSignal.timeout(2000) 
        })
        if (res.ok) return true
      } catch {
        // 后端未就绪，继续等待
      }
      await new Promise(resolve => setTimeout(resolve, retryDelay))
    }
    return false
  }, [])

  /**
   * 从后端获取文档列表
   * @param isInitial 是否为首次加载（首次加载会等待后端就绪）
   */
  const fetchDocuments = useCallback(async (isInitial = false) => {
    if (isInitial) {
      setInitialLoading(true)
      // 首次加载时，先等待后端就绪
      const ready = await waitForBackend()
      if (!ready) {
        message.error('后端服务启动超时，请重启应用')
        setInitialLoading(false)
        return
      }
    }

    try {
      const res = await fetch(`${API_BASE}/documents`)
      if (!res.ok) throw new Error('获取文档列表失败')
      const data = await res.json()
      setDocuments(data.documents)
    } catch (err) {
      console.error('Failed to fetch documents:', err)
      // 非首次加载时静默失败，不显示错误（可能是网络波动）
    } finally {
      if (isInitial) {
        setInitialLoading(false)
      }
    }
  }, [waitForBackend])

  // -------- 轮询逻辑 --------

  /** 检查是否有文档正在处理 */
  const hasProcessingDocs = documents.some(
    (doc) => doc.status === 'pending' || doc.status === 'processing'
  )

  /**
   * 当有文档处理中时，每 2 秒轮询一次状态
   * 使用 isInitial=false 避免闪烁
   */
  useEffect(() => {
    if (!hasProcessingDocs) return

    const interval = setInterval(() => {
      fetchDocuments(false) // 静默更新，不显示 loading
    }, 2000)

    return () => clearInterval(interval)
  }, [hasProcessingDocs, fetchDocuments])

  // 首次加载
  useEffect(() => {
    fetchDocuments(true)
  }, [fetchDocuments])

  // -------- 文件上传 --------

  /** 上传单个文件到后端 */
  const uploadFile = async (filePath: string): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE}/documents/upload`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: filePath }),
      })

      if (res.ok) {
        const doc = await res.json()
        message.success(`上传成功: ${doc.name}`)
        return true
      }

      // 处理错误
      const errData = await res.json()
      if (res.status === 409) {
        message.warning(errData.detail || '文件已存在')
      } else {
        message.error(errData.detail || '上传失败')
      }
      return false
    } catch (err) {
      message.error(`上传失败: ${err}`)
      return false
    }
  }

  /** 处理文件路径（来自拖拽或选择） */
  const handleFilePaths = useCallback(async (paths: string[]) => {
    const supportedPaths = paths.filter(isSupportedFile)
    
    if (supportedPaths.length === 0) {
      message.warning('请拖拽 PDF 或 CHM 文件')
      return
    }

    setUploading(true)
    
    // 逐个上传文件
    let successCount = 0
    for (const path of supportedPaths) {
      if (await uploadFile(path)) {
        successCount++
      }
    }

    // 刷新文档列表（静默更新）
    await fetchDocuments(false)
    setUploading(false)

    if (successCount > 0) {
      message.info(`成功上传 ${successCount} 个文件`)
    }
  }, [fetchDocuments])

  /** 通过 Tauri 对话框选择文件 */
  const handleSelectFiles = useCallback(async () => {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const selected = await open({
        multiple: true,
        filters: [{ name: '文档', extensions: ['pdf', 'chm'] }],
      })
      
      if (!selected) return // 用户取消
      
      const paths = Array.isArray(selected) ? selected : [selected]
      await handleFilePaths(paths)
    } catch (err) {
      message.error(`选择文件失败: ${err}`)
    }
  }, [handleFilePaths])

  // -------- Tauri 原生拖拽 --------

  useEffect(() => {
    let unlisten: (() => void) | null = null

    const setupDragDrop = async () => {
      try {
        const { getCurrentWindow } = await import('@tauri-apps/api/window')
        
        unlisten = await getCurrentWindow().onDragDropEvent((event) => {
          const payload = (event as DragDropEvent).payload
          
          if (payload.type === 'enter' || payload.type === 'over') {
            setIsDragging(true)
          } else if (payload.type === 'drop') {
            setIsDragging(false)
            
            // 防抖：500ms 内重复事件忽略
            const now = Date.now()
            if (now - lastDropTimeRef.current < 500) return
            lastDropTimeRef.current = now
            
            if (payload.paths && payload.paths.length > 0) {
              handleFilePaths(payload.paths)
            }
          } else if (payload.type === 'leave' || payload.type === 'cancel') {
            setIsDragging(false)
          }
        })
      } catch {
        // Tauri API 不可用（浏览器环境）
      }
    }

    setupDragDrop()

    return () => {
      if (unlisten) unlisten()
    }
  }, [handleFilePaths])

  // -------- 删除文档 --------

  const handleDelete = async (docId: string) => {
    try {
      const res = await fetch(`${API_BASE}/documents/${docId}`, {
        method: 'DELETE',
      })
      
      if (!res.ok) throw new Error('删除失败')
      
      message.success('已删除文档')
      await fetchDocuments(false) // 静默更新
    } catch (err) {
      message.error(`删除失败: ${err}`)
    }
  }

  // -------- 重新处理文档 --------

  const handleReprocess = async (docId: string) => {
    try {
      const res = await fetch(`${API_BASE}/documents/${docId}/reprocess`, {
        method: 'POST',
      })
      
      if (!res.ok) throw new Error('重新处理失败')
      
      const data = await res.json()
      message.success(`开始重新处理，已删除 ${data.deleted_chunks} 条旧数据`)
      await fetchDocuments(false)
    } catch (err) {
      message.error(`重新处理失败: ${err}`)
    }
  }

  // -------- 重新处理全部文档 --------

  const handleReprocessAll = async () => {
    setReprocessingAll(true)
    try {
      const res = await fetch(`${API_BASE}/documents/reprocess-all`, {
        method: 'POST',
      })
      
      if (!res.ok) throw new Error('重新处理失败')
      
      const data = await res.json()
      message.success(`开始重新处理 ${data.total} 个文档`)
      await fetchDocuments(false)
    } catch (err) {
      message.error(`重新处理失败: ${err}`)
    } finally {
      setReprocessingAll(false)
    }
  }

  // -------- 渲染 --------

  return (
    <div className="knowledge-base-view">
      <div className="kb-header">
        <h2>知识库管理</h2>
        <p className="kb-description">
          上传 PDF 或 CHM 文档，系统会自动解析并建立索引，方便后续查询。
        </p>
      </div>

      {/* 上传区域 */}
      <Card className="upload-card">
        <div
          className={`upload-area ${isDragging ? 'dragging' : ''}`}
          onClick={handleSelectFiles}
        >
          <InboxOutlined className="upload-icon" />
          <p className="upload-text">点击或拖拽文件到此区域上传</p>
          <p className="upload-hint">支持 PDF 和 CHM 格式</p>
        </div>
        <div className="upload-actions">
          <Button
            icon={<UploadOutlined />}
            onClick={handleSelectFiles}
            loading={uploading}
          >
            选择文件
          </Button>
        </div>
      </Card>

      {/* 文档列表 */}
      <Card 
        className="document-list-card" 
        title={`已上传文档 (${documents.length})`}
        extra={
          documents.length > 0 && (
            <Popconfirm
              title="重新处理全部文档？"
              description="将删除所有向量数据并重新解析"
              onConfirm={handleReprocessAll}
              okText="确定"
              cancelText="取消"
            >
              <Button
                type="text"
                icon={<SyncOutlined />}
                loading={reprocessingAll}
                size="small"
              >
                重建索引
              </Button>
            </Popconfirm>
          )
        }
        loading={initialLoading} // 仅首次加载显示 loading
      >
        {documents.length === 0 ? (
          <Empty
            description="暂无文档，请上传 PDF 或 CHM 文件"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        ) : (
          <List
            dataSource={documents}
            renderItem={(doc) => (
              <List.Item
                actions={[
                  // 重新处理按钮（仅 ready 状态显示）
                  doc.status === 'ready' && (
                    <Button
                      key="reprocess"
                      type="text"
                      icon={<ReloadOutlined />}
                      size="small"
                      title="重新处理"
                      onClick={() => handleReprocess(doc.id)}
                    />
                  ),
                  <Popconfirm
                    key="delete"
                    title="确认删除此文档？"
                    description="删除后无法恢复"
                    onConfirm={() => handleDelete(doc.id)}
                    okText="删除"
                    cancelText="取消"
                  >
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      size="small"
                    />
                  </Popconfirm>,
                ].filter(Boolean)}
              >
                <List.Item.Meta
                  avatar={
                    doc.file_type === 'chm' ? (
                      <FileTextOutlined className="doc-icon" style={{ color: '#1890ff' }} />
                    ) : (
                      <FilePdfOutlined className="doc-icon" style={{ color: '#f5222d' }} />
                    )
                  }
                  title={doc.name}
                  description={
                    <>
                      <Tag style={{ marginRight: 4 }}>{doc.file_type.toUpperCase()}</Tag>
                      {formatFileSize(doc.size)}
                      {doc.chunk_count !== null && doc.chunk_count > 0 && (
                        <span> · {doc.chunk_count} 个片段</span>
                      )}
                      <span> · {new Date(doc.uploaded_at).toLocaleString()}</span>
                    </>
                  }
                />
                {/* 状态标签 */}
                <Tag color={statusConfig[doc.status]?.color || 'default'}>
                  {statusConfig[doc.status]?.text || doc.status}
                </Tag>
              </List.Item>
            )}
          />
        )}
      </Card>
    </div>
  )
}

export default KnowledgeBaseView
