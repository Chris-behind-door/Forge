import { useState, useRef, useEffect, useCallback } from 'react'
import { Button, Card, message } from 'antd'
import { UploadOutlined, InboxOutlined } from '@ant-design/icons'
import { getApiBase } from '../api'

const isSupportedFile = (name: string): boolean => {
  const ext = name.toLowerCase().split('.').pop()
  return ext === 'pdf' || ext === 'chm'
}

interface Props {
  selectedProjectId: string | null
  selectedProjectName: string
  onUploadComplete: () => void
}

export default function UploadArea({ selectedProjectId, selectedProjectName, onUploadComplete }: Props) {
  const [uploading, setUploading] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const isUploadingRef = useRef(false)
  const dropCountRef = useRef(0)

  const uploadFile = async (filePath: string): Promise<boolean> => {
    try {
      const body: Record<string, string | null> = { file_path: filePath, project_id: selectedProjectId }
      const res = await fetch(`${getApiBase()}/documents/upload`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      if (res.ok) { const doc = await res.json(); message.success(`上传成功: ${doc.name}`); return true }
      const errData = await res.json()
      if (res.status === 409) message.warning(errData.detail || '文件已存在')
      else message.error(errData.detail || '上传失败')
      return false
    } catch (err) { message.error(`上传失败: ${err}`); return false }
  }

  const handleFilePaths = useCallback(async (paths: string[]) => {
    if (isUploadingRef.current) return
    const supportedPaths = paths.filter(isSupportedFile)
    if (supportedPaths.length === 0) { message.warning('请拖拽 PDF 或 CHM 文件'); return }
    isUploadingRef.current = true
    setUploading(true)
    let successCount = 0
    for (const path of supportedPaths) { if (await uploadFile(path)) successCount++ }
    onUploadComplete()
    setUploading(false)
    isUploadingRef.current = false
    if (successCount > 0) message.info(`成功上传 ${successCount} 个文件`)
  }, [onUploadComplete, selectedProjectId])

  const handleSelectFiles = useCallback(async () => {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const selected = await open({ multiple: true, filters: [{ name: '文档', extensions: ['pdf', 'chm'] }] })
      if (!selected) return
      const paths = Array.isArray(selected) ? selected : [selected]
      await handleFilePaths(paths)
    } catch (err) { message.error(`选择文件失败: ${err}`) }
  }, [handleFilePaths])

  // Tauri drag-drop — use refs to avoid closure staleness and listener stacking
  const handleFilePathsRef = useRef(handleFilePaths)
  handleFilePathsRef.current = handleFilePaths

  useEffect(() => {
    let unlisten: (() => void) | undefined

    const setup = async () => {
      try {
        const { getCurrentWindow } = await import('@tauri-apps/api/window')
        unlisten = await getCurrentWindow().onDragDropEvent((event: any) => {
          const payload = event.payload
          if (payload.type === 'enter' || payload.type === 'over') {
            setIsDragging(true)
          } else if (payload.type === 'drop') {
            setIsDragging(false)
            // Deduplicate: only accept the first drop in a batch
            dropCountRef.current++
            const thisDrop = dropCountRef.current
            setTimeout(() => {
              if (thisDrop === dropCountRef.current && payload.paths?.length) {
                handleFilePathsRef.current(payload.paths)
              }
            }, 100)
          } else if (payload.type === 'leave' || payload.type === 'cancel') {
            setIsDragging(false)
          }
        })
      } catch { /* not Tauri */ }
    }

    setup()

    return () => {
      if (unlisten) unlisten()
    }
  }, []) // stable — no deps, uses refs

  return (
    <Card className="upload-card">
      <p style={{ marginBottom: 12, color: '#666' }}>
        向「<strong>{selectedProjectName}</strong>」导入文档
      </p>
      <div className={`upload-area ${isDragging ? 'dragging' : ''}`} onClick={handleSelectFiles}>
        <InboxOutlined className="upload-icon" />
        <p className="upload-text">点击或拖拽文件到此区域上传</p>
        <p className="upload-hint">支持 PDF 和 CHM 格式</p>
      </div>
      <div className="upload-actions">
        <Button icon={<UploadOutlined />} onClick={handleSelectFiles} loading={uploading}>选择文件</Button>
      </div>
    </Card>
  )
}
