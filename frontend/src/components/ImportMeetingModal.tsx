import { useState } from 'react'
import { Modal, Form, Input, DatePicker, Upload, Button, Alert, Card, Tag, message } from 'antd'
import { UploadOutlined, CheckCircleOutlined } from '@ant-design/icons'
import { getApiBase } from '../api'

const LONG_OP_HINT = '处理可能需要几分钟，请耐心等待。'

interface Props {
  open: boolean
  onClose: () => void
  projectId: string
  onImported: () => void
}

export default function ImportMeetingModal({ open, onClose, projectId, onImported }: Props) {
  const [importForm] = Form.useForm()
  const [importLoading, setImportLoading] = useState(false)
  const [extractResult, setExtractResult] = useState<{
    meeting: any; resolutions: any[]; relations: any[]; message: string
  } | null>(null)

  const handleClose = () => {
    onClose()
    setExtractResult(null)
    importForm.resetFields()
    setImportLoading(false)
  }

  return (
    <Modal
      title="导入会议纪要"
      open={open}
      onCancel={handleClose}
      cancelText="取消"
      okText={importLoading ? '处理中...' : '导入并提取'}
      footer={extractResult ? [
        <Button key="close" type="primary" onClick={handleClose}>确定</Button>,
      ] : undefined}
      onOk={() => importForm.submit()}
      confirmLoading={importLoading}
      okButtonProps={{ disabled: importLoading }}
      cancelButtonProps={{ disabled: importLoading }}
      width={720}
    >
      {extractResult ? (
        <div>
          <div style={{ marginBottom: 12, padding: '8px 12px', background: '#f6ffed', borderRadius: 6, border: '1px solid #b7eb8f' }}>
            <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
            {extractResult.message}
          </div>
          {extractResult.resolutions.length > 0 && (
            <div>
              <h4 style={{ margin: '12px 0 8px' }}>提取的决议：</h4>
              {extractResult.resolutions.map((r: any, idx: number) => (
                <Card key={r.id || idx} size="small" style={{ marginBottom: 8, borderLeft: '3px solid #52c41a' }}>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>决议 {r.index}</div>
                  <div style={{ color: '#444', fontSize: 13 }}>{r.content}</div>
                </Card>
              ))}
            </div>
          )}
          {extractResult.relations.length > 0 && (
            <div>
              <h4 style={{ margin: '12px 0 8px' }}>检测到的关联：</h4>
              {extractResult.relations.map((rel: any, idx: number) => (
                <div key={idx} style={{ marginBottom: 6, fontSize: 13, color: '#555' }}>
                  <Tag color={rel.type === 'SUPERSEDES' ? 'red' : rel.type === 'AMENDS' ? 'orange' : 'blue'}>
                    {rel.type === 'SUPERSEDES' ? '替代' : rel.type === 'AMENDS' ? '修订' : '补充'}
                  </Tag>
                  <span>{rel.reason}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div>
          <Alert type="info" showIcon message="上传文件后将自动提取决议并建立跨会议关联"
            description={LONG_OP_HINT} style={{ marginBottom: 16 }} />
          <Form form={importForm} layout="vertical" onFinish={async (values) => {
            if (!projectId || !values.file?.[0]) return
            setImportLoading(true)
            try {
              const formData = new FormData()
              formData.append('file', values.file[0])
              formData.append('date', values.date?.format('YYYY-MM-DD') || '')
              formData.append('title', values.title || '')
              const res = await fetch(`${getApiBase()}/projects/${projectId}/meetings/import`, {
                method: 'POST', body: formData,
              })
              if (res.ok) {
                const data = await res.json()
                message.success(data.message || '导入成功')
                onImported()
                handleClose()
              } else { const err = await res.json(); message.error(err.detail || '导入失败') }
            } catch { message.error('导入失败') }
            setImportLoading(false)
          }}>
            <Form.Item name="file" label="纪要文件" rules={[{ required: true, message: '请选择文件' }]}>
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
        </div>
      )}
    </Modal>
  )
}
