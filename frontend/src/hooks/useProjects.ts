import { useState, useEffect, useCallback } from 'react'
import { message } from 'antd'
import { getApiBase } from '../api'
import type { Project } from '../types'

export function useProjects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(false)

  const fetchProjects = useCallback(async () => {
    try {
      const res = await fetch(`${getApiBase()}/projects`)
      if (res.ok) {
        setProjects(await res.json())
      }
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetchProjects() }, [fetchProjects])

  const createProject = useCallback(async (name: string, description?: string) => {
    try {
      const res = await fetch(`${getApiBase()}/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.detail || '创建失败')
      }
      message.success('项目已创建')
      await fetchProjects()
      return true
    } catch (err) {
      message.error(err instanceof Error ? err.message : '创建失败')
      return false
    }
  }, [fetchProjects])

  const updateProject = useCallback(async (id: string, data: { name?: string; description?: string }) => {
    try {
      const res = await fetch(`${getApiBase()}/projects/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error('更新失败')
      message.success('项目已更新')
      await fetchProjects()
      return true
    } catch (err) {
      message.error(err instanceof Error ? err.message : '更新失败')
      return false
    }
  }, [fetchProjects])

  const deleteProject = useCallback(async (id: string) => {
    try {
      const res = await fetch(`${getApiBase()}/projects/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('删除失败')
      message.success('项目已删除')
      await fetchProjects()
      return true
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除失败')
      return false
    }
  }, [fetchProjects])

  return { projects, loading, setLoading, fetchProjects, createProject, updateProject, deleteProject }
}
