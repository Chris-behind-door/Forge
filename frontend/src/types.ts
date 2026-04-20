/**
 * 共享类型定义
 */

export interface Project {
  id: string
  name: string
  description?: string
  meeting_count?: number
  resolution_count?: number
  created_at?: string
}

export interface Citation {
  doc_id: string
  doc_name: string
  chunk_index: number | null
  page: number | null
  location: string | null
  text_snippet: string
}
