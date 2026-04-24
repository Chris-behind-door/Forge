import { useState, useRef } from 'react'
import { Modal, Form, Input, DatePicker, Upload, Button, Alert, message } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { getApiBase } from '../api'

interface Props {
  open: boolean
  onClose: () => void
  projectId: string
  onImported: () => void
}

export default function ImportMeetingModal({ open, onClose, projectId, onImported }: Props) {
  const [importForm] = Form.useForm()
  const [importLoading, setImportLoading] = useState(false)
  const [hasFile, setHasFile] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const handleClose = () => {
    // Cancel in-flight request if user closes during import
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    setImportLoading(false)
    setHasFile(false)
    importForm.resetFields()
    onClose()
  }

  // Reset state when modal opens
  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) handleClose()
  }

  return (
    <Modal
      title="导入会议纪要"
      open={open}
      onCancel={handleClose}
      afterOpenChange={handleOpenChange}
      maskClosable={!importLoading}
      closable={!importLoading}
      cancelText="取消"
      okText={importLoading ? '处理中...' : '导入并提取'}
      onOk={() => importForm.submit()}
      confirmLoading={importLoading}
      okButtonProps={{ disabled: importLoading || !hasFile }}
      cancelButtonProps={{ disabled: importLoading }}
      width={720}
    >
      <Alert
        type="info" showIcon
        message="上传文件后将自动提取决议并建立跨会议关联"
        description="处理可能需要几分钟，请耐心等待。导入过程中请勿关闭窗口。"
        style={{ marginBottom: 16 }}
      />
      <Form form={importForm} layout="vertical" onFinish={async (values) => {
        if (!projectId || importLoading) return
        const file = values.file?.[0]?.originFileObj
        if (!file) return
        setImportLoading(true)
        const controller = new AbortController()
        abortRef.current = controller
        try {
          const formData = new FormData()
          formData.append('file', file as File)
          formData.append('date', values.date?.format('YYYY-MM-DD') || '')
          formData.append('title', values.title || '')
          const res = await fetch(`${getApiBase()}/projects/${projectId}/meetings/import`, {
            method: 'POST',
            body: formData,
            signal: controller.signal,
          })
          if (res.ok) {
            const data = await res.json()
            message.success(data.message || '导入成功')
            onImported()
            handleClose()
          } else {
            const err = await res.json()
            message.error(err.detail || '导入失败')
          }
        } catch (e: any) {
          if (e.name !== 'AbortError') {
            message.error('导入失败')
          }
        } finally {
          setImportLoading(false)
          abortRef.current = null
        }
      }}>
        <Form.Item name="file" label="纪要文件" rules={[{ required: true, message: '请选择文件' }]} valuePropName="fileList" getValueFromEvent={(e) => {
          const fileList = Array.isArray(e) ? e : e?.fileList || []
          setHasFile(fileList.length > 0)
          return fileList
        }}>
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
    </Modal>
  )
}
