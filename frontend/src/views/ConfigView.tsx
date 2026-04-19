/**
 * ConfigView - LLM 配置界面（SillyTavern 风格）
 */
import { useState, useEffect, useCallback } from 'react'
import { Card, Select, Input, Button, Form, message, Space, Alert, Divider, Tag, Popconfirm } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, LinkOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { listen } from '@tauri-apps/api/event'
import './ConfigView.css'

interface ProviderInfo {
  id: string
  name: string
  has_key: boolean
  default_base_url: string
  default_model: string
}

interface ActiveConfig {
  provider: string | null
  model: string | null
  base_url: string | null
}

interface LlmConfig {
  providers: ProviderInfo[]
  active: ActiveConfig
}

interface CustomProfile {
  name: string
  base_url: string
  model: string
}

import { getApiBase } from '../api'
const CUSTOM_PROFILES_KEY = 'llm_custom_profiles'
const PROVIDER_MODELS_KEY = 'llm_provider_models_v2'

function loadJson<T>(key: string, fallback: T): T {
  try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : fallback } catch { return fallback }
}

function saveJson(key: string, data: unknown) { localStorage.setItem(key, JSON.stringify(data)) }

function ConfigView() {
  const [config, setConfig] = useState<LlmConfig | null>(null)
  const [loading, setLoading] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ status: string; detail?: string } | null>(null)
  const [customProfiles, setCustomProfiles] = useState<CustomProfile[]>(() => loadJson(CUSTOM_PROFILES_KEY, []))
  const [providerModels, setProviderModels] = useState<Record<string, string>>(() => {
    // 清除旧版本的数据（格式可能不兼容）
    try { localStorage.removeItem('llm_provider_models') } catch {}
    return {}
  })

  const [preset, setPreset] = useState<string>('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [newProfileName, setNewProfileName] = useState('')
  const [ipcToken, setIpcToken] = useState<string | null>(null)

  useEffect(() => {
    const unlisten = listen<string>('ipc-token', (event) => setIpcToken(event.payload))
    return () => { unlisten.then((fn) => fn()) }
  }, [])

  const fetchConfig = useCallback(async () => {
    try {
      const headers: Record<string, string> = {}
      if (ipcToken) headers['Authorization'] = `Bearer ${ipcToken}`
      const res = await fetch(`${getApiBase()}/config/llm`, { headers })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: LlmConfig = await res.json()
      setConfig(data)

      if (data.active.provider) {
        setPreset(data.active.provider)
        setBaseUrl(data.active.base_url || '')
        setModel(data.active.model || '')
        // 同步记住当前活跃 provider 的 model
        if (data.active.model) {
          const updated = { ...providerModels, [data.active.provider]: data.active.model }
          setProviderModels(updated)
          saveJson(PROVIDER_MODELS_KEY, updated)
        }
      }
    } catch (e) {
      console.error('[ConfigView] fetchConfig failed:', e)
      // 避免 StrictMode double-mount 重复报错
      message.error({
        content: '无法获取配置',
        key: 'fetch-config-error',
        duration: 3,
      })
    }
  }, [ipcToken])

  useEffect(() => { fetchConfig() }, [fetchConfig])

  const hasExistingKey = (() => {
    if (!preset) return false
    // 自定义预设检查 custom provider
    const checkProvider = preset.startsWith('custom:') ? 'custom' : preset
    return config?.providers.find(p => p.id === checkProvider)?.has_key || false
  })()

  const handlePresetChange = (value: string) => {
    setPreset(value)
    setTestResult(null)
    setApiKey('')

    let url = ''
    let mdl = ''

    if (value.startsWith('custom:')) {
      const profile = customProfiles.find(p => `custom:${p.name}` === value)
      if (profile) { url = profile.base_url; mdl = profile.model; setNewProfileName(profile.name) }
    } else {
      setNewProfileName('')
      const prov = config?.providers.find(p => p.id === value)
      if (prov) {
        url = prov.default_base_url
        // 优先用上次为该 provider 保存的 model，其次用默认值
        mdl = providerModels[value] || prov.default_model
      }
    }
    setBaseUrl(url)
    setModel(mdl)
  }

  const handleTest = async () => {
    const keyToUse = apiKey || ''
    if (!baseUrl || !model) { message.warning('请先填写 Base URL 和模型名称'); return }
    if (!keyToUse && !hasExistingKey) { message.warning('请输入 API Key'); return }

    setTesting(true)
    setTestResult(null)
    try {
      const body: Record<string, string | null> = { base_url: baseUrl, api_key: apiKey || null, model }
      if (preset) {
        body.provider = preset.startsWith('custom:') ? 'custom' : preset
      }

      const res = await fetch(`${getApiBase()}/config/llm/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      setTestResult(data)
    } catch { setTestResult({ status: 'error', detail: '网络请求失败' }) }
    finally { setTesting(false) }
  }

  const handleSave = async () => {
    if (!preset) { message.warning('请选择一个预设'); return }
    const actualProvider = preset.startsWith('custom:') ? 'custom' : preset

    // 记住这个 provider 的 model
    const updatedModels = { ...providerModels, [actualProvider]: model }
    setProviderModels(updatedModels)
    saveJson(PROVIDER_MODELS_KEY, updatedModels)

    setLoading(true)
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (ipcToken) headers['Authorization'] = `Bearer ${ipcToken}`
      const body: Record<string, string> = { provider: actualProvider }
      if (apiKey) body.api_key = apiKey
      if (model) body.model = model
      if (baseUrl) body.base_url = baseUrl

      const res = await fetch(`${getApiBase()}/config/llm`, { method: 'POST', headers, body: JSON.stringify(body) })
      if (!res.ok) { const err = await res.json().catch(() => null); throw new Error(err?.detail || `HTTP ${res.status}`) }

      message.success('配置已保存')
      setApiKey('')
      await fetchConfig()
    } catch (error) { message.error(error instanceof Error ? error.message : '保存失败') }
    finally { setLoading(false) }
  }

  const handleSaveCustomProfile = async () => {
    const name = newProfileName.trim()
    if (!name) { message.warning('请输入配置名称'); return }
    if (!baseUrl || !model) { message.warning('请先填写 Base URL 和模型名称'); return }

    // 保存 key 到后端（custom provider）
    if (apiKey) {
      try {
        const headers: Record<string, string> = { 'Content-Type': 'application/json' }
        if (ipcToken) headers['Authorization'] = `Bearer ${ipcToken}`
        await fetch(`${getApiBase()}/config/llm`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ provider: 'custom', api_key: apiKey, model, base_url: baseUrl }),
        })
      } catch { /* 静默失败，profile 本地保存不受影响 */ }
    } else if (hasExistingKey) {
      // 没填新 key 但当前 preset 有 key，让后端从原始 provider 迁移
      const sourceProvider = preset.startsWith('custom:') ? undefined : preset
      try {
        const headers: Record<string, string> = { 'Content-Type': 'application/json' }
        if (ipcToken) headers['Authorization'] = `Bearer ${ipcToken}`
        await fetch(`${getApiBase()}/config/llm`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ provider: 'custom', model, base_url: baseUrl, migrate_from: sourceProvider }),
        })
      } catch { /* 静默 */ }
    }

    const updated = customProfiles.some(p => p.name === name)
      ? customProfiles.map(p => p.name === name ? { ...p, base_url: baseUrl, model } : p)
      : [...customProfiles, { name, base_url: baseUrl, model }]
    setCustomProfiles(updated)
    saveJson(CUSTOM_PROFILES_KEY, updated)
    message.success('配置已保存')
    setNewProfileName('')
  }

  const handleDeleteCustomProfile = (name: string) => {
    const updated = customProfiles.filter(p => p.name !== name)
    setCustomProfiles(updated)
    saveJson(CUSTOM_PROFILES_KEY, updated)
    if (preset === `custom:${name}`) setPreset('')
    message.success('配置已删除')
  }

  if (!config) return <div style={{ padding: 24, color: '#999' }}>加载中...</div>

  const activeProviderName = config.active.provider
    ? config.providers.find(p => p.id === config.active.provider)?.name || config.active.provider
    : null

  return (
    <div className="config-view">
      <h2>模型配置</h2>

      {activeProviderName && config.active.model && (
        <Alert
          type="success"
          showIcon
          message={
            <Space>
              当前：{activeProviderName} / {config.active.model}
              {config.active.base_url && <Tag color="orange">自定义 URL</Tag>}
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      <Card title="API 连接配置" size="small">
        <Form layout="vertical">
          <Form.Item label="预设">
            <Select
              value={preset || undefined}
              onChange={handlePresetChange}
              placeholder="选择预设"
              options={[
                ...config.providers.map((p) => ({
                  value: p.id,
                  label: <Space>{p.name}{p.has_key && <Tag color="green">已配置</Tag>}</Space>,
                })),
                ...customProfiles.map((p) => ({
                  value: `custom:${p.name}`,
                  label: <Space>⭐ {p.name}<Tag color="blue">{p.model}</Tag></Space>,
                })),
              ]}
            />
          </Form.Item>

          <Divider style={{ margin: '8px 0' }}>连接参数</Divider>

          <Form.Item label="Base URL" extra="/chat/completions 后缀会自动补全">
            <Input value={baseUrl} onChange={(e) => { setBaseUrl(e.target.value); setTestResult(null) }} placeholder="https://open.bigmodel.cn/api/paas/v4" />
          </Form.Item>

          <Form.Item label="API Key">
            <Input.Password value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={hasExistingKey ? '留空则使用已保存的 Key' : '输入 API Key'} />
          </Form.Item>

          <Form.Item label="模型名称">
            <Input value={model} onChange={(e) => { setModel(e.target.value); setTestResult(null) }} placeholder="glm-4.7" />
          </Form.Item>

          <Form.Item label="连接测试">
            <Space>
              <Button icon={<LinkOutlined />} onClick={handleTest} loading={testing} disabled={!baseUrl || !model || (!apiKey && !hasExistingKey)}>连接</Button>
              {testResult && testResult.status === 'ok' ? (
                <Tag icon={<CheckCircleOutlined />} color="success">连接成功</Tag>
              ) : testResult ? (
                <Tag icon={<CloseCircleOutlined />} color="error">{testResult.detail}</Tag>
              ) : null}
            </Space>
          </Form.Item>

          <Divider style={{ margin: '8px 0' }} />

          <Form.Item label="保存为自定义配置">
            <Space>
              <Input value={newProfileName} onChange={(e) => setNewProfileName(e.target.value)} placeholder="配置名称" style={{ width: 200 }} />
              <Button icon={<PlusOutlined />} onClick={handleSaveCustomProfile}>{newProfileName && customProfiles.some(p => p.name === newProfileName.trim()) ? '覆盖保存' : '保存'}</Button>
            </Space>
          </Form.Item>

          {customProfiles.length > 0 && (
            <Form.Item label="已保存的自定义配置">
              <div className="custom-profile-list">
                {customProfiles.map((p) => (
                  <div key={p.name} className="custom-profile-item">
                    <span className="profile-name">⭐ {p.name}</span>
                    <span className="profile-detail">{p.model}</span>
                    <Popconfirm title={`删除配置「${p.name}」？`} onConfirm={() => handleDeleteCustomProfile(p.name)}>
                      <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </div>
                ))}
              </div>
            </Form.Item>
          )}

          <Form.Item>
            <Button type="primary" onClick={handleSave} loading={loading}>应用配置</Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}

export default ConfigView
