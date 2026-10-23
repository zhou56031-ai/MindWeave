import client from './client'
import type { ApiResponse } from '../types/api'

export interface SessionUsage {
  session_id: string
  title: string
  requests: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  model_calls: number
  tool_calls: number
  duration_ms: number
  avg_duration_ms: number
  last_at: string | null
  created_at: string | null
}

export interface UsageRequest {
  trace_id: string
  created_at: string | null
  status: string
  duration_ms: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  model_calls: number
  tool_calls: number
}

export const usageApi = {
  summary: async (days: number) => {
    const res = await client.get<ApiResponse<{ days: number; sessions: SessionUsage[] }>>('/chat/usage', { params: { days } })
    return res.data
  },
  detail: async (sessionId: string, days: number) => {
    const res = await client.get<ApiResponse<{ session_id: string; title: string; requests: UsageRequest[] }>>(
      `/chat/usage/${sessionId}`, { params: { days } },
    )
    return res.data
  },
}
