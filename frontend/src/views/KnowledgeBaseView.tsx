/**
 * KnowledgeBaseView - 文档管理界面（主布局）
 */
import { useState, useEffect, useCallback } from 'react'
import { Modal, Input, Form, message } from 'antd'
import { getApiBase } from '../api'
import { useProjects } from '../hooks/useProjects'
import ProjectSelector from '../components/ProjectSelector'
import UploadArea from '../components/UploadArea'
import DocumentList from '../components/DocumentList'
import './KnowledgeBaseView.css'

interface Document {
  id: string
  name: string
  size: number
  file_type: 'pdf' | 'chm'
  uploaded_at: string
  status: 'pending' | 'processing' | 'ready' | 'error'
  chunk_count: number | null
  project_id: string | null
}

function KnowledgeBaseView() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const { projects, createProject, updateProject, deleteProject } = useProjects()

  // Project modal
  const [projectModalOpen, setProjectModalOpen] = useState(false)
  const [editingProject, setEditingProject] = useState<{ id: string; name: string; description: string } | null>(null)
  const [projectForm] = Form.useForm()

  // -------- Data --------

  const waitForBackend = useCallback(async (maxRetries = 10, retryDelay = 500) => {
    for (let i = 0; i < maxRetries; i++) {
      try {
        const res = await fetch(`${getApiBase()}/health`, { signal: AbortSignal.timeout(2000) })
        if (res.ok) return true
      } catch { /* not ready */ }
      await new Promise(resolve => setTimeout(resolve, retryDelay))
    }
    return false
  }, [])

  const fetchDocuments = useCallback(async (isInitial = false) => {
    if (isInitial) {
      setInitialLoading(true)
      const ready = await waitForBackend()
      if (!ready) { message.error('后端服务启动超时，请重启应用'); setInitialLoading(false); return }
    }
    try {
      const params = new URLSearchParams()
      if (selectedProjectId !== null) params.set('project_id', selectedProjectId)
      else params.set('filter_null', 'true')
      const query = params.toString() ? `?${params.toString()}` : ''
      const res = await fetch(`${getApiBase()}/documents${query}`)
      if (!res.ok) throw new Error('获取文档列表失败')
      setDocuments((await res.json()).documents)
    } catch (err) {
      console.error('Failed to fetch documents:', err)
    } finally {
      if (isInitial) setInitialLoading(false)
    }
  }, [waitForBackend, selectedProjectId])

  // Polling
  const hasProcessingDocs = documents.some(d => d.status === 'pending' || d.status === 'processing')
  useEffect(() => {
    if (!hasProcessingDocs) return
    const interval = setInterval(() => fetchDocuments(false), 2000)
    return () => clearInterval(interval)
  }, [hasProcessingDocs, fetchDocuments])

  useEffect(() => { fetchDocuments(true) }, [fetchDocuments])

  // -------- Project handlers --------

  const handleCreateProject = () => { setEditingProject(null); projectForm.resetFields(); setProjectModalOpen(true) }
  const handleEditProject = (project: { id: string; name: string; description?: string }) => {
    setEditingProject({ id: project.id, name: project.name, description: project.description || '' })
    projectForm.setFieldsValue({ name: project.name, description: project.description || '' })
    setProjectModalOpen(true)
  }
  const handleProjectModalOk = async () => {
    try {
      const values = await projectForm.validateFields()
      if (editingProject) await updateProject(editingProject.id, values)
      else await createProject(values.name, values.description)
      setProjectModalOpen(false)
    } catch { /* validation */ }
  }
  const handleDeleteProject = async (projectId: string) => {
    await deleteProject(projectId)
    if (selectedProjectId === projectId) setSelectedProjectId(null)
  }

  const selectedProjectName = selectedProjectId === null
    ? '通用知识' : projects.find(p => p.id === selectedProjectId)?.name || '未知项目'

  return (
    <div className="knowledge-base-view">
      <div className="kb-header">
        <h2>知识库管理</h2>
        <p className="kb-description">上传 PDF 或 CHM 文档，系统会自动解析并建立索引，方便后续查询。</p>
      </div>

      <ProjectSelector
        projects={projects} selectedProjectId={selectedProjectId}
        onSelect={setSelectedProjectId} onCreate={handleCreateProject}
        onEdit={handleEditProject} onDelete={handleDeleteProject}
      />

      <Modal title={editingProject ? '编辑项目' : '新建项目'} open={projectModalOpen}
        onOk={handleProjectModalOk} onCancel={() => setProjectModalOpen(false)}
        okText={editingProject ? '保存' : '创建'} cancelText="取消">
        <Form form={projectForm} layout="vertical">
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}>
            <Input placeholder="输入项目名称" />
          </Form.Item>
          <Form.Item name="description" label="项目描述">
            <Input.TextArea placeholder="输入项目描述（可选）" rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      <UploadArea
        selectedProjectId={selectedProjectId}
        selectedProjectName={selectedProjectName}
        onUploadComplete={() => fetchDocuments(false)}
      />

      <DocumentList
        documents={documents} projects={projects}
        loading={initialLoading}
        onRefresh={() => fetchDocuments(false)}
      />
    </div>
  )
}

export default KnowledgeBaseView
