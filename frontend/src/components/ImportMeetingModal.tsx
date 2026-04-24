import { useState } from 'react'
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

  const handleClose = () => {
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
      okText={importLoading ? '上传中...' : '导入并提取'}
      onOk={() => importForm.submit()}
      confirmLoading={importLoading}
      okButtonProps={{ disabled: importLoading || !hasFile }}
      cancelButtonProps={{ disabled: importLoading }}
      width={720}
    >
      <Alert
        type="info" showIcon
        message="上传文件后将自动加入处理队列"
        description="文件上传后会排队等待 AI 处理，您可以在会议列表中查看处理进度。"
        style={{ marginBottom: 16 }}
      />
      <Form form={importForm} layout="vertical" onFinish={async (values) => {
        if (!projectId || importLoading) return
        const file = values.file?.[0]?.originFileObj
        if (!file) return
        setImportLoading(true)
        try {
          const formData = new FormData()
          formData.append('file', file as File)
          formData.append('date', values.date?.format('YYYY-MM-DD') || '')
          formData.append('title', values.title || '')
          const res = await fetch(`${getApiBase()}/projects/${projectId}/meetings/import`, {
            method: 'POST',
            body: formData,
          })
          if (res.ok) {
            const data = await res.json()
            message.success(data.message || '已加入处理队列')
            onImported()
            handleClose()
          } else {
            const err = await res.json()
            message.error(err.detail || '导入失败')
          }
        } catch {
          message.error('导入失败')
        } finally {
          setImportLoading(false)
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
