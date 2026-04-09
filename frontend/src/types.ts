/**
 * 共享类型定义
 */

export interface Citation {
  doc_id: string
  doc_name: string
  chunk_index: number | null
  page: number | null
  location: string | null
  text_snippet: string
}
