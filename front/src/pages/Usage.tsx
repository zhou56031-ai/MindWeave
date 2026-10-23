import { Fragment, useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, ChevronDown, ChevronRight, Loader2, RefreshCw } from 'lucide-react'
import { usageApi } from '../api/usage'
import type { SessionUsage, UsageRequest } from '../api/usage'

const RANGES = [7, 30, 90]

function formatTokens(value: number): string {
  return value.toLocaleString('zh-CN')
}

function formatDuration(ms: number): string {
  if (!ms) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

function formatTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export default function Usage() {
  const [days, setDays] = useState(30)
  const [sessions, setSessions] = useState<SessionUsage[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [details, setDetails] = useState<Record<string, UsageRequest[]>>({})
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await usageApi.summary(days)
      setSessions(data.data.sessions)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => { void load() }, [load])

  const toggle = async (sessionId: string) => {
    if (expanded === sessionId) {
      setExpanded(null)
      return
    }
    setExpanded(sessionId)
    if (!details[sessionId]) {
      try {
        const data = await usageApi.detail(sessionId, days)
        setDetails((prev) => ({ ...prev, [sessionId]: data.data.requests }))
      } catch {
        setDetails((prev) => ({ ...prev, [sessionId]: [] }))
      }
    }
  }

  const totals = sessions.reduce(
    (acc, item) => ({
      tokens: acc.tokens + item.total_tokens,
      duration: acc.duration + item.duration_ms,
      requests: acc.requests + item.requests,
    }),
    { tokens: 0, duration: 0, requests: 0 },
  )

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="font-heading text-2xl font-semibold text-[var(--color-text)]">用量与耗时</h1>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            按会话汇总每次问答的 token、模型调用与耗时；数据来自请求 trace。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-[3px] border border-[var(--color-border)] p-0.5">
            {RANGES.map((range) => (
              <button
                key={range}
                onClick={() => setDays(range)}
                className={`rounded-[2px] px-2.5 py-1 text-xs ${
                  days === range
                    ? 'bg-[var(--color-accent)] text-[var(--color-accent-contrast)]'
                    : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]'
                }`}
              >
                {range} 天
              </button>
            ))}
          </div>
          <button
            onClick={() => void load()}
            className="flex h-8 w-8 items-center justify-center rounded-[3px] border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
            title="刷新"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          ['会话数', String(sessions.length)],
          ['请求数', formatTokens(totals.requests)],
          ['总 token', formatTokens(totals.tokens)],
          ['总耗时', formatDuration(totals.duration)],
        ].map(([label, value]) => (
          <div key={label} className="rounded-[4px] border border-[var(--color-border)] bg-[var(--color-card)] px-4 py-3">
            <div className="text-xs text-[var(--color-text-tertiary)]">{label}</div>
            <div className="mt-1 text-xl font-semibold text-[var(--color-text)]">{value}</div>
          </div>
        ))}
      </div>

      {error && (
        <div className="mb-4 rounded-[4px] border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-4 py-3 text-sm text-[var(--color-text-secondary)]">
          {error}
        </div>
      )}

      <div className="overflow-hidden rounded-[4px] border border-[var(--color-border)] bg-[var(--color-card)]">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-tertiary)]">
              <th className="px-4 py-3 font-medium">会话</th>
              <th className="px-3 py-3 font-medium">请求</th>
              <th className="px-3 py-3 font-medium">输入 token</th>
              <th className="px-3 py-3 font-medium">输出 token</th>
              <th className="px-3 py-3 font-medium">模型调用</th>
              <th className="px-3 py-3 font-medium">总耗时</th>
              <th className="px-3 py-3 font-medium">最近</th>
              <th className="w-10 px-3 py-3" />
            </tr>
          </thead>
          <tbody>
            {loading && sessions.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-[var(--color-text-secondary)]">
                  <Loader2 size={18} className="mx-auto animate-spin" />
                </td>
              </tr>
            ) : sessions.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-[var(--color-text-secondary)]">
                  <Activity size={22} className="mx-auto mb-2" />
                  还没有可统计的对话
                </td>
              </tr>
            ) : (
              sessions.map((item) => (
                <Fragment key={item.session_id}>
                  <tr
                    onClick={() => void toggle(item.session_id)}
                    className="cursor-pointer border-b border-[var(--color-border)] last:border-b-0 hover:bg-[var(--color-bg-secondary)]"
                  >
                    <td className="max-w-[220px] truncate px-4 py-3 text-[var(--color-text)]">
                      {item.requests > 0 ? (
                        <Link
                          to={`/chat/${item.session_id}`}
                          onClick={(event) => event.stopPropagation()}
                          className="hover:underline"
                        >
                          {item.title}
                        </Link>
                      ) : item.title}
                    </td>
                    <td className="px-3 py-3 text-[var(--color-text-secondary)]">{item.requests}</td>
                    <td className="px-3 py-3 text-[var(--color-text-secondary)]">{formatTokens(item.input_tokens)}</td>
                    <td className="px-3 py-3 text-[var(--color-text-secondary)]">{formatTokens(item.output_tokens)}</td>
                    <td className="px-3 py-3 text-[var(--color-text-secondary)]">{item.model_calls}</td>
                    <td className="px-3 py-3 text-[var(--color-text-secondary)]">
                      {formatDuration(item.duration_ms)}
                      <span className="ml-1 text-xs text-[var(--color-text-tertiary)]">
                        (平均 {formatDuration(item.avg_duration_ms)})
                      </span>
                    </td>
                    <td className="px-3 py-3 text-xs text-[var(--color-text-tertiary)]">{formatTime(item.last_at)}</td>
                    <td className="px-3 py-3 text-[var(--color-text-tertiary)]">
                      {expanded === item.session_id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </td>
                  </tr>
                  {expanded === item.session_id && (
                    <tr key={`${item.session_id}-detail`} className="border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
                      <td colSpan={8} className="px-6 py-4">
                        {!(details[item.session_id]?.length) ? (
                          <div className="text-xs text-[var(--color-text-secondary)]">没有请求明细</div>
                        ) : (
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="text-left text-[var(--color-text-tertiary)]">
                                <th className="py-1 font-medium">时间</th>
                                <th className="py-1 font-medium">状态</th>
                                <th className="py-1 font-medium">输入</th>
                                <th className="py-1 font-medium">输出</th>
                                <th className="py-1 font-medium">模型调用</th>
                                <th className="py-1 font-medium">工具</th>
                                <th className="py-1 font-medium">耗时</th>
                              </tr>
                            </thead>
                            <tbody>
                              {details[item.session_id].map((row) => (
                                <tr key={row.trace_id} className="text-[var(--color-text-secondary)]">
                                  <td className="py-1">{formatTime(row.created_at)}</td>
                                  <td className="py-1">{row.status}</td>
                                  <td className="py-1">{formatTokens(row.input_tokens)}</td>
                                  <td className="py-1">{formatTokens(row.output_tokens)}</td>
                                  <td className="py-1">{row.model_calls}</td>
                                  <td className="py-1">{row.tool_calls}</td>
                                  <td className="py-1">{formatDuration(row.duration_ms)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
