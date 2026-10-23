import client from './client'
import type { ApiResponse } from '../types/api'

export interface MemoryItem {
  id: string
  content: string
  created_at: string | null
}

export interface MemoryOverview {
  summary: string
  count: number
  items: MemoryItem[]
}

export const memoryApi = {
  list: async () => {
    const res = await client.get<ApiResponse<MemoryOverview>>('/user/memories/')
    return res.data.data
  },
  add: async (content: string) => {
    const res = await client.post<ApiResponse<{ id: string; content: string }>>('/user/memories/', { content })
    return res.data.data
  },
  remove: async (id: string) => {
    await client.delete(`/user/memories/${id}`)
  },
}
