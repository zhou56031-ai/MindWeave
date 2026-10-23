import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Send, Bot, User, ChevronDown, ChevronRight, Loader2, ChevronsDownUp, ChevronsUpDown } from 'lucide-react'
import BrandMark from '../components/common/BrandMark'
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import rehypeRaw from 'rehype-raw'
import remarkGfm from 'remark-gfm'
import { useSSE } from '../hooks/useSSE'
import { sessionsApi } from '../api/sessions'
import { useThemeStore } from '../stores/useThemeStore'
import { endpoints } from '../api/endpoints'
import type { ApprovalPayload, SSEMessage, SourceItem, UsageInfo } from '../types/api'
import { isEvidenceEvent, isReadableRetrievalStatus, isRetrievalStage, isVisibleThinkingStage, mergeThinkingStep, previewEvidence, retrievalStatusLabel, thinkingStepTitle, toEvidence } from '../utils/thinkingTrace'
import type { ThinkingStep } from '../utils/thinkingTrace'

interface Message {
  role: 'user' | 'assistant'
  content: string
  thinking?: string
  steps?: string[]
  sources?: SourceItem[]
  usage?: UsageInfo
}

function mergeSources(previous: SourceItem[], next?: SourceItem[]): SourceItem[] {
  if (!next?.length) return previous
  const map = new Map(previous.map((item) => [item.id, item]))
  for (const item of next) {
    if (item?.id) map.set(item.id, item)
  }
  return [...map.values()]
}

const quickQuestions = [
  '帮我解释一下量子计算',
  '写一首关于春天的诗',
  '推荐几本提升思维的书',
]

const evidenceSourceLabels: Record<string, string> = {
  note: '笔记',
  knowledge_base: '知识库',
  graph: '知识图谱',
  web: 'Web',
  web_search: 'Web search',
}

const retrievalToolLabels: Record<string, string> = {
  hybrid_search: '混合检索',
  search_graph: '知识图谱检索',
  search_notes: '笔记检索',
  search_knowledge_base: '知识库检索',
  web_search: 'Web 检索',
}

const approvalToolLabels: Record<string, string> = {
  create_note: '创建笔记',
  create_note_tool: '创建笔记',
  mark_reviewed: '完成回顾',
}

const APPROVAL_PREVIEW_LIMIT = 240
const APPROVAL_ARG_LIMIT = 200

function truncateText(text: string, limit: number): string {
  if (text.length <= limit) return text
  return `${text.slice(0, limit)}…`
}

function stripMarkdown(text: string): string {
  return text
    .replace(/```[^\n]*\n?/g, '')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^>\s?/gm, '')
    .replace(/^\s*(?:[-*+]|\d+[.)])\s+/gm, '')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/^---+\s*$/gm, '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
    .join('\n')
}

export default function AIChat() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const { t } = useTranslation()
  const theme = useThemeStore((s) => s.theme)
  const { start, loading } = useSSE()
  const [pendingApproval, setPendingApproval] = useState<{
    runId: string
    payload: ApprovalPayload
    sessionId: string | null
  } | null>(null)
  const [approveSubmitting, setApproveSubmitting] = useState(false)
  const [approvalNotice, setApprovalNotice] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [currentThinking, setCurrentThinking] = useState('')
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([])
  const [expandedEvidence, setExpandedEvidence] = useState<Record<string, boolean>>({})
  const [expandedApproval, setExpandedApproval] = useState<Record<string, boolean>>({})
  const [showThinking, setShowThinking] = useState(true)
  const [loadingHistory, setLoadingHistory] = useState(false)
  // 会话切换时在 render 阶段同步重置审批与历史加载态（与原 effect 语义一致，避免 effect 内同步 setState）
  const [prevSessionId, setPrevSessionId] = useState<string | undefined | null>(null)
  if (sessionId !== prevSessionId) {
    setPrevSessionId(sessionId)
    setPendingApproval(null)
    setApprovalNotice(null)
    setRejectReason('')
    setLoadingHistory(!!sessionId)
  }
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef('')
  const rafRef = useRef<number | null>(null)
  const pendingThinkingRef = useRef<ThinkingStep[]>([])
  const sourcesRef = useRef<SourceItem[]>([])
  const usageRef = useRef<UsageInfo | undefined>(undefined)
  const thinkingTimerRef = useRef<number | null>(null)
  const thinkingGenerationRef = useRef(0)
  const thinkingManuallyCollapsedRef = useRef(false)
  const thinkingTerminalGenerationRef = useRef<number | null>(null)
  // 流式完成后跳转会话会触发历史加载；跳过这一次，避免覆盖 sources/usage。
  const skipHistoryRef = useRef<string | null>(null)

  const logicalThinkingKey = (step: ThinkingStep) => {
    if (step.stage !== 'supplemental_retrieval') return step.stage
    const query = step.details?.query
    return `${step.stage}:${typeof query === 'string' ? query : ''}`
  }

  const mergeIncomingThinkingStep = (steps: ThinkingStep[], next: ThinkingStep) => {
    const nextKey = logicalThinkingKey(next)
    const placeholderIndex = steps.findIndex((step) => (
      logicalThinkingKey(step) === nextKey && step.details?.placeholder
    ))
    if (placeholderIndex !== -1) {
      const replaced = [...steps]
      replaced[placeholderIndex] = next
      return replaced
    }

    if (isRetrievalStage(next.stage)) {
      const existingIdx = steps.findIndex((step) => logicalThinkingKey(step) === nextKey)
      if (existingIdx !== -1) {
        const merged = [...steps]
        merged[existingIdx] = mergeThinkingStep(merged[existingIdx], next)
        return merged
      }
    }

    return [...steps, next]
  }

  const flushContent = useCallback(() => {
    setMessages((prev) => {
      const newMsgs = [...prev]
      const last = newMsgs[newMsgs.length - 1]
      const patch = {
        content: contentRef.current,
        sources: sourcesRef.current,
        usage: usageRef.current,
      }
      if (last?.role === 'assistant') {
        newMsgs[newMsgs.length - 1] = { ...last, ...patch }
      } else {
        newMsgs.push({ role: 'assistant', ...patch })
      }
      return newMsgs
    })
  }, [])

  const cancelPendingThinking = useCallback(() => {
    thinkingGenerationRef.current += 1
    pendingThinkingRef.current = []
    if (thinkingTimerRef.current !== null) {
      clearTimeout(thinkingTimerRef.current)
      thinkingTimerRef.current = null
    }
  }, [])

  useEffect(() => {
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      cancelPendingThinking()
    }
  }, [cancelPendingThinking])

  const fetchPendingApproval = useCallback(async () => {
    // 新会话 URL 可能没有 :sessionId 参数，用流里见过的会话 id 兜底
    const sid = sessionId ?? sessionStorage.getItem('lastSessionId')
    if (!sid) return
    try {
      const res = await sessionsApi.getPending(sid)
      const data = res.data as {
        run_id?: string
        payload?: ApprovalPayload
        query?: string
      } | null
      if (data?.run_id && data?.payload) {
        setPendingApproval({ runId: data.run_id, payload: data.payload, sessionId: sid })
        if (data.query) {
          setMessages((prev) => [...prev, { role: 'user', content: data.query ?? '' }])
        }
      } else {
        setPendingApproval(null)
      }
    } catch {
      // 静默失败：用户仍可重发消息触发后端守卫提示
    }
  }, [sessionId])

  useEffect(() => {
    if (sessionId) {
      if (skipHistoryRef.current === sessionId) {
        skipHistoryRef.current = null
        setLoadingHistory(false)
        return
      }
      sessionsApi.get(sessionId).then((res) => {
        const data = res.data as { history?: [string, string][]; pending_run_id?: string | null } | undefined
        if (data?.history) {
          const entries = data.history
          const roleFormat = entries.length > 0 && entries.every(([role]) =>
            role === 'user' || role === 'assistant' || role === 'system' || role === 'tool',
          )
          const mapped: Message[] = roleFormat
            ? entries
                .filter(([role]) => role === 'user' || role === 'assistant')
                .map(([role, content]) => ({ role: role as 'user' | 'assistant', content }))
            : entries.flatMap(([query, response]) => [
                { role: 'user' as const, content: query },
                { role: 'assistant' as const, content: response },
              ])
          setMessages(mapped)
        }
        if (data?.pending_run_id) {
          fetchPendingApproval()
        }
      }).catch(() => {}).finally(() => setLoadingHistory(false))
    }
  }, [sessionId, fetchPendingApproval])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, currentThinking])

  useEffect(() => {
    if (!sessionId) {
      const lastId = sessionStorage.getItem('lastSessionId')
      if (lastId) {
        navigate(`/chat/${lastId}`, { replace: true })
      }
    }
  }, [sessionId, navigate])

  const handleSend = useCallback(async (query: string) => {
    if (!query.trim() || loading || pendingApproval) return

    const userMsg: Message = { role: 'user', content: query }
    cancelPendingThinking()
    const requestGeneration = thinkingGenerationRef.current
    thinkingManuallyCollapsedRef.current = false
    thinkingTerminalGenerationRef.current = null
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setCurrentThinking('')
    setThinkingSteps([])
    setShowThinking(true)

    contentRef.current = ''
    sourcesRef.current = []
    usageRef.current = undefined
    let hasResponseStarted = false

    await start(
      '/chat/agent/query/stream',
      { query, session_id: sessionId },
      {
        onThinking: (stage, content, details) => {
          if (thinkingGenerationRef.current !== requestGeneration || thinkingTerminalGenerationRef.current === requestGeneration) return
          if (!isVisibleThinkingStage(stage)) return
          if (!thinkingManuallyCollapsedRef.current) setShowThinking(true)
          const results = isEvidenceEvent(stage, details) && Array.isArray(details?.results)
            ? details.results.map(toEvidence).filter((item) => item !== null)
            : []
          if (isEvidenceEvent(stage, details) && results.length === 0) return
          const step: ThinkingStep = {
            stage,
            content: content || '',
            details,
            ...(results.length > 0 ? { evidence: results } : {}),
          }
          if (details?.status === 'searching') {
            setThinkingSteps((prev) => {
              const nextKey = logicalThinkingKey(step)
              const existingIdx = prev.findIndex((item) => logicalThinkingKey(item) === nextKey)
              if (existingIdx === -1) return [...prev, step]
              const merged = [...prev]
              merged[existingIdx] = mergeThinkingStep(merged[existingIdx], step)
              return merged
            })
            return
          }
          const isPlaceholder = Boolean(details?.placeholder)
          if (isPlaceholder) {
            // 占位事件立即落地，让「正在规划」折叠框第一时间出现
            setThinkingSteps((prev) => [...prev, step])
            return
          }
          // 真实步骤加入待渲染队列，按 150ms 间隔逐个 flush，形成依次推进的节奏；
          // 若上一步是占位（同 stage），则替换而非新增，避免叠两条。
          pendingThinkingRef.current.push(step)
          setCurrentThinking((prev) => prev ? `${prev}\n${content}` : (content || ''))
          if (thinkingTimerRef.current !== null) return
          const flushOne = () => {
            if (thinkingGenerationRef.current !== requestGeneration) {
              thinkingTimerRef.current = null
              return
            }
            const next = pendingThinkingRef.current.shift()
            if (!next) {
              thinkingTimerRef.current = null
              return
            }
            setThinkingSteps((prev) => {
              return mergeIncomingThinkingStep(prev, next)
            })
            thinkingTimerRef.current = window.setTimeout(flushOne, 150)
          }
          thinkingTimerRef.current = window.setTimeout(flushOne, 150)
        },
        onResponse: (content, sessionId, meta) => {
          if (thinkingGenerationRef.current !== requestGeneration || thinkingTerminalGenerationRef.current === requestGeneration) return
          if (!hasResponseStarted) {
            hasResponseStarted = true
          }
          if (sessionId) {
            sessionStorage.setItem('lastSessionId', sessionId)
          }
          sourcesRef.current = mergeSources(sourcesRef.current, meta?.sources)
          if (meta?.usage) usageRef.current = meta.usage
          contentRef.current += content
          if (rafRef.current === null) {
            rafRef.current = requestAnimationFrame(() => {
              rafRef.current = null
              if (thinkingGenerationRef.current !== requestGeneration || thinkingTerminalGenerationRef.current === requestGeneration) return
              flushContent()
            })
          }
        },
        onInterrupt: (msg: SSEMessage) => {
          if (!msg.run_id || !msg.payload) return
          // interrupt 帧自带 session_id：新会话 URL 无参数时靠它恢复审批
          setPendingApproval({ runId: msg.run_id, payload: msg.payload, sessionId: msg.session_id ?? null })
        },
        onDone: (newSessionId) => {
          if (thinkingGenerationRef.current !== requestGeneration || thinkingTerminalGenerationRef.current === requestGeneration) return
          if (rafRef.current !== null) {
            cancelAnimationFrame(rafRef.current)
            rafRef.current = null
          }
          flushContent()
          const pending = pendingThinkingRef.current.splice(0)
          if (pending.length > 0) {
            setThinkingSteps((prev) => pending.reduce(mergeIncomingThinkingStep, prev))
          }
          cancelPendingThinking()
          if (!thinkingManuallyCollapsedRef.current) setShowThinking(true)
          if (newSessionId) {
            sessionStorage.setItem('lastSessionId', newSessionId)
          }
          if (newSessionId && newSessionId !== sessionId) {
            skipHistoryRef.current = newSessionId
            navigate(`/chat/${newSessionId}`, { replace: true })
          }
        },
        onError: (error) => {
          if (thinkingGenerationRef.current !== requestGeneration || thinkingTerminalGenerationRef.current === requestGeneration) return
          if (error === 'PENDING_EXISTS' && sessionId) {
            // 会话尚有未决审批：拉取 pending 恢复审批卡，不显示错误气泡
            fetchPendingApproval()
            return
          }
          const pending = pendingThinkingRef.current.splice(0)
          if (pending.length > 0) {
            setThinkingSteps((prev) => pending.reduce(mergeIncomingThinkingStep, prev))
          }
          if (rafRef.current !== null) {
            cancelAnimationFrame(rafRef.current)
            rafRef.current = null
          }
          thinkingTerminalGenerationRef.current = requestGeneration
          cancelPendingThinking()
          setMessages((prev) => [...prev, { role: 'assistant', content: `Error: ${error}` }])
        },
      }
    )
  }, [loading, sessionId, start, navigate, flushContent, cancelPendingThinking, pendingApproval, fetchPendingApproval])

  const handleApprove = async () => {
    if (!pendingApproval || approveSubmitting) return
    await resolveApproval([{ type: 'approve' }])
  }

  const handleReject = async () => {
    if (!pendingApproval || approveSubmitting) return
    await resolveApproval([{ type: 'reject', message: rejectReason.trim() || '用户拒绝了该操作' }])
    setRejectReason('')
  }

  const resolveApproval = async (decisions: Array<Record<string, unknown>>) => {
    const snapshot = pendingApproval
    if (!snapshot) return
    // session_id 多级兜底：审批卡自带的 > URL 参数 > 流里见过的（新会话 URL 无参数时前两者都可能为空）
    const sid = snapshot.sessionId ?? sessionId ?? sessionStorage.getItem('lastSessionId')
    if (!sid) {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Error: 无法确定会话，请刷新页面后重试' }])
      return
    }
    // 先关弹窗再跑流：resume 全程可能几十秒，弹窗不能一直卡着按钮
    const approved = decisions[0]?.type === 'approve'
    const actionCount = snapshot.payload.action_requests.length
    setPendingApproval(null)
    setApprovalNotice(approved ? `已同意 ${actionCount} 个操作，正在执行…` : '已拒绝该操作，正在处理…')
    setApproveSubmitting(true)
    contentRef.current = ''
    sourcesRef.current = []
    usageRef.current = undefined
    const requestGeneration = thinkingGenerationRef.current
    thinkingManuallyCollapsedRef.current = false
    setShowThinking(true)
    // onError 之后后端还会补一个 done 帧，用 failed 区分，避免 done 把错误现场清掉
    let failed = false
    try {
      await start(
        endpoints.agentResume,
        { session_id: sid, decisions },
        {
          onThinking: (stage, content, details) => {
            if (thinkingGenerationRef.current !== requestGeneration) return
            if (!isVisibleThinkingStage(stage)) return
            if (!thinkingManuallyCollapsedRef.current) setShowThinking(true)
            const step: ThinkingStep = {
              stage, content: content || '', details,
            }
            setThinkingSteps((prev) => mergeIncomingThinkingStep(prev, step))
          },
          onResponse: (content, _sid, meta) => {
            if (thinkingGenerationRef.current !== requestGeneration) return
            sourcesRef.current = mergeSources(sourcesRef.current, meta?.sources)
            if (meta?.usage) usageRef.current = meta.usage
            contentRef.current += content
            if (rafRef.current === null) {
              rafRef.current = requestAnimationFrame(() => {
                rafRef.current = null
                if (thinkingGenerationRef.current !== requestGeneration) return
                flushContent()
              })
            }
          },
          onInterrupt: (msg) => {
            if (!msg.run_id || !msg.payload) return
            setPendingApproval({ runId: msg.run_id, payload: msg.payload, sessionId: msg.session_id ?? null })
          },
          onDone: () => {
            if (rafRef.current !== null) {
              cancelAnimationFrame(rafRef.current)
              rafRef.current = null
            }
            if (!failed) {
              flushContent()
              cancelPendingThinking()
              if (!thinkingManuallyCollapsedRef.current) setShowThinking(true)
            }
            setApprovalNotice(null)
            setApproveSubmitting(false)
          },
          onError: (error) => {
            failed = true
            setApprovalNotice(null)
            setApproveSubmitting(false)
            setMessages((prev) => [...prev, { role: 'assistant', content: `Error: ${error}` }])
            // 后端出错保留 thread 与 pending 供重试：恢复审批卡；
            // 若中途已来新审批（二次中断）则不动；切走会话也不恢复旧卡
            if (sid === (sessionId ?? sessionStorage.getItem('lastSessionId'))) {
              setPendingApproval((prev) => prev ?? snapshot)
            }
          },
        },
      )
    } finally {
      setApproveSubmitting(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend(input)
    }
  }

  const isLoading = loadingHistory || loading
  const hasStreamingAssistant = loading && messages.length > 0 && messages[messages.length - 1].role === 'assistant'

  const thinkingPanel = thinkingSteps.length > 0 ? (
    <div className="bg-[var(--color-card)] rounded-lg border border-[var(--color-border)] overflow-hidden">
      <button
        onClick={() => setShowThinking((previous) => {
          const next = !previous
          thinkingManuallyCollapsedRef.current = !next
          return next
        })}
        className="flex items-center justify-between gap-2 px-4 py-2.5 text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] w-full text-left"
      >
        <span className="flex items-center gap-2">
          {showThinking ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {t('chat.thinkingSteps')} ({thinkingSteps.length})
        </span>
        {loading && <Loader2 size={13} className="animate-spin" />}
      </button>
      {showThinking && (
        <div className="px-4 pb-3 space-y-2">
          {thinkingSteps.map((step, index) => (
            <details key={`${step.stage}-${index}`} open={index === thinkingSteps.length - 1} className="rounded-md bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
              <summary className="cursor-pointer list-none px-3 py-2 text-xs text-[var(--color-text)] flex items-center justify-between gap-3">
                <span className="font-medium" title={step.stage}>{index + 1}. {thinkingStepTitle(step)}</span>
                <span className="text-[var(--color-text-tertiary)]">
                  {isReadableRetrievalStatus(step.stage, step.details) ? retrievalStatusLabel(step.details?.status, step.stage) : ''}
                </span>
              </summary>
              <div className="px-3 pb-3 space-y-2 text-xs text-[var(--color-text-secondary)]">
                {isReadableRetrievalStatus(step.stage, step.details) && (
                  <p className="leading-relaxed whitespace-pre-wrap">{retrievalStatusLabel(step.details?.status, step.stage)}</p>
                )}
                {['agentic_plan', 'answerability', 'evidence_fusion', 'tool_execution', 'tool_start', 'tool_end', 'local_retrieval'].includes(step.stage) && (
                  <p className="leading-relaxed whitespace-pre-wrap">{step.content}</p>
                )}
                {step.stage === 'agentic_plan' && step.details && (
                  <div className="space-y-1 text-[var(--color-text-tertiary)]">
                    {typeof step.details.reason === 'string' && <p>Reason: {step.details.reason}</p>}
                    {typeof step.details.source === 'string' && <p>Source: {step.details.source}</p>}
                    {typeof step.details.step_count === 'number' && <p>Retrieval steps: {step.details.step_count}</p>}
                    {Array.isArray(step.details.steps) && step.details.steps.length > 0 && (
                      <div className="pt-2 space-y-2">
                        <p className="font-medium text-[var(--color-text-secondary)]">具体调用</p>
                        {step.details.steps.map((rawStep, planIndex) => {
                          if (typeof rawStep !== 'object' || rawStep === null || Array.isArray(rawStep)) return null
                          const planStep = rawStep as Record<string, unknown>
                          const tool = typeof planStep.tool === 'string' ? planStep.tool : 'unknown'
                          const query = typeof planStep.query === 'string' ? planStep.query : ''
                          const topK = typeof planStep.top_k === 'number' ? planStep.top_k : null
                          return (
                            <div key={`${tool}-${planIndex}`} className="rounded border border-[var(--color-border)] bg-[var(--color-bg)] p-2 space-y-1">
                              <p className="text-[var(--color-text)]">{retrievalToolLabels[tool] || tool}</p>
                              {query && <p>查询：{query}</p>}
                              {topK !== null && <p>数量：{topK}</p>}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )}
                {isEvidenceEvent(step.stage, step.details) && step.evidence && step.evidence.length > 0 ? (
                  <div className="space-y-2">
                    {step.evidence.map((evidence, evidenceIndex) => (
                      (() => {
                        const evidenceKey = `${step.stage}:${evidence.source}:${evidence.id}:${evidenceIndex}`
                        const isExpanded = expandedEvidence[evidenceKey] === true
                        const hasMore = evidence.preview.length > 200
                        return <div key={evidenceKey} className="rounded border border-[var(--color-border)] bg-[var(--color-bg)] p-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-[var(--color-text)]">{evidence.title}</span>
                          {evidence.score !== undefined && evidence.score !== null && <span>{evidence.score}</span>}
                        </div>
                        <div className="text-[var(--color-text-tertiary)]">{evidenceSourceLabels[evidence.source] || evidence.source || 'Unknown source'}</div>
                        <p className="mt-1 whitespace-pre-wrap">{isExpanded ? evidence.preview : previewEvidence(evidence.preview)}</p>
                        {hasMore && (
                          <button
                            type="button"
                            aria-expanded={isExpanded}
                            aria-label={isExpanded ? 'Collapse evidence' : 'Expand evidence'}
                            onClick={() => setExpandedEvidence((previous) => ({ ...previous, [evidenceKey]: !isExpanded }))}
                            className="mt-1 inline-flex items-center gap-1 text-[var(--color-accent)] hover:underline"
                          >
                            {isExpanded ? <ChevronsUpDown size={13} /> : <ChevronsDownUp size={13} />}
                            {isExpanded ? '收起' : '展开全文'}
                          </button>
                        )}
                      </div>
                      })()
                    ))}
                  </div>
                ) : null}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  ) : null

  return (
    <div className="h-full flex flex-col">
      {messages.length > 0 && (
        <div className="shrink-0 px-6 py-3 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
          <div className="max-w-3xl mx-auto flex justify-end">
            <button
              onClick={() => {
                sessionStorage.removeItem('lastSessionId')
                setMessages([])
                navigate('/chat')
              }}
              className="px-3 py-1.5 text-xs rounded-md border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] transition-colors"
            >
              {t('chat.newSession')}
            </button>
          </div>
        </div>
      )}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.length === 0 && !isLoading && (
            <div className="py-20 text-center">
              <div className="mb-6 flex justify-center">
                <BrandMark size={40} className="text-[var(--color-text)]" />
              </div>
              <h2 className="font-heading text-[22px] leading-tight text-[var(--color-text)]">{t('chat.welcome')}</h2>
              <p className="mx-auto mt-2 max-w-sm text-[13px] leading-relaxed text-[var(--color-text-tertiary)]">
                {t('chat.welcomeSub')}
              </p>
              <div className="mx-auto mt-7 flex max-w-md flex-wrap justify-center gap-2">
                {quickQuestions.map((q) => (
                  <button
                    key={q}
                    onClick={() => handleSend(q)}
                    className="rounded-[3px] border border-[var(--color-border)] px-3.5 py-1.5 text-xs text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:bg-[var(--color-accent)] hover:text-[var(--color-accent-contrast)]"
                  >
                    {q}
                  </button>
                ))}
              </div>
              <p className="mx-auto mt-8 max-w-sm text-[11px] leading-relaxed tracking-wide text-[var(--color-text-tertiary)]">
                {t('chat.emptyHint')}
              </p>
            </div>
          )}

          {loadingHistory && (
            <div className="flex justify-center py-4">
              <Loader2 size={20} className="animate-spin text-[var(--color-text-tertiary)]" />
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : ''}`}>
              {msg.role === 'assistant' && (
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[3px] border border-[var(--color-border)] bg-[var(--color-card)]">
                  <Bot size={15} className="text-[var(--color-text-secondary)]" />
                </div>
              )}
              <div className={`max-w-[75%] ${msg.role === 'user' ? 'order-first' : ''}`}>
                {msg.role === 'user' ? (
                  <div className="rounded-[10px] bg-[var(--color-accent)] px-4 py-2.5 text-sm text-[var(--color-accent-contrast)]">
                    {msg.content}
                  </div>
                ) : (
                  <>
                    {i === messages.length - 1 && thinkingPanel && (
                      <div className="mb-3">
                        {thinkingPanel}
                      </div>
                    )}
                    <div className={`prose prose-sm max-w-none markdown-body${theme === 'dark' ? ' prose-invert' : ''}`}>
                      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight, rehypeRaw]}>
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                    {!!msg.sources?.length && (
                      <div className="mt-3 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-3">
                        <div className="mb-2 text-xs font-medium text-[var(--color-text-secondary)]">
                          引用来源（{msg.sources.length}）
                        </div>
                        <ol className="space-y-2">
                          {msg.sources.map((source, index) => (
                            <li key={source.id} className="text-xs leading-relaxed">
                              <span className="mr-1 text-[var(--color-text-tertiary)]">[{index + 1}]</span>
                              <span className="font-medium text-[var(--color-text)]">{source.title || source.id}</span>
                              {source.source && (
                                <span className="ml-2 text-[var(--color-text-tertiary)]">
                                  {evidenceSourceLabels[source.source] || source.source}
                                </span>
                              )}
                              {typeof source.score === 'number' && (
                                <span className="ml-2 text-[var(--color-text-tertiary)]">score {source.score}</span>
                              )}
                              {source.preview && (
                                <p className="mt-1 line-clamp-2 text-[var(--color-text-secondary)]">{source.preview}</p>
                              )}
                            </li>
                          ))}
                        </ol>
                      </div>
                    )}
                    {msg.usage && (
                      <div className="mt-2 text-[11px] text-[var(--color-text-tertiary)]">
                        tokens {msg.usage.input_tokens ?? 0} 输入 / {msg.usage.output_tokens ?? 0} 输出
                        {typeof msg.usage.duration_ms === 'number' && ` · 耗时 ${(msg.usage.duration_ms / 1000).toFixed(1)}s`}
                        {typeof msg.usage.calls === 'number' && ` · ${msg.usage.calls} 次模型调用`}
                      </div>
                    )}
                    {hasStreamingAssistant && i === messages.length - 1 && (
                      <div className="flex gap-1 mt-3">
                        <span className="w-2 h-2 rounded-full bg-[var(--color-accent)] animate-bounce" style={{ animationDelay: '0ms' }} />
                        <span className="w-2 h-2 rounded-full bg-[var(--color-accent)] animate-bounce" style={{ animationDelay: '150ms' }} />
                        <span className="w-2 h-2 rounded-full bg-[var(--color-accent)] animate-bounce" style={{ animationDelay: '300ms' }} />
                      </div>
                    )}
                  </>
                )}
              </div>
              {msg.role === 'user' && (
                <div className="w-8 h-8 rounded-lg bg-[var(--color-bg-tertiary)] flex items-center justify-center shrink-0">
                  <User size={16} className="text-[var(--color-text-secondary)]" />
                </div>
              )}
            </div>
          ))}

          {loading && !hasStreamingAssistant && (
            <div className="flex gap-3">
              <div className="w-8 h-8 rounded-lg bg-[var(--color-accent-bg)] flex items-center justify-center shrink-0">
                <Bot size={16} className="text-[var(--color-accent)]" />
              </div>
              <div className="space-y-2 flex-1">
                {thinkingPanel}
                <div className="flex gap-1">
                  <span className="w-2 h-2 rounded-full bg-[var(--color-accent)] animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-2 h-2 rounded-full bg-[var(--color-accent)] animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-2 h-2 rounded-full bg-[var(--color-accent)] animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {!pendingApproval && approveSubmitting && approvalNotice && (
        <div className="max-w-3xl mx-auto px-6 pt-4">
          <div className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] px-4 py-2.5 text-xs text-[var(--color-text-secondary)]">
            <Loader2 size={13} className="animate-spin shrink-0" />
            {approvalNotice}
          </div>
        </div>
      )}

      {pendingApproval && (
        <div className="max-w-3xl mx-auto px-6 pt-4">
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] p-4 space-y-3">
            <div className="text-sm font-medium text-[var(--color-text)]">
              需要确认以下操作
            </div>
            {pendingApproval.payload.action_requests.map((req, i) => {
              const expandKey = `${pendingApproval.runId}:${i}`
              const expanded = expandedApproval[expandKey] === true
              const toggleExpanded = () => setExpandedApproval((prev) => ({ ...prev, [expandKey]: !expanded }))
              const args = req.args ?? {}
              const title = typeof args.title === 'string' ? args.title : ''
              const content = typeof args.content === 'string' ? args.content : ''
              const isNote = (
                req.name === 'create_note' || req.name === 'create_note_tool'
              ) && (title !== '' || content !== '')
              const description = req.description ?? ''
              const descExpanded = expandedApproval[`${expandKey}:desc`] === true
              return (
                <div key={`${req.name}-${i}`} className="rounded-md bg-[var(--color-bg-secondary)] p-3 text-xs space-y-2">
                  <div className="font-medium text-[var(--color-text)] text-sm">
                    {approvalToolLabels[req.name] || req.name}
                    <span className="ml-2 font-normal text-[var(--color-text-tertiary)]">{req.name}</span>
                  </div>
                  {description !== '' && (
                    <p className={`leading-relaxed text-[var(--color-text-secondary)]${descExpanded ? ' max-h-96 overflow-y-auto pr-2' : ''}`}>
                      {descExpanded ? stripMarkdown(description) : truncateText(stripMarkdown(description), APPROVAL_PREVIEW_LIMIT)}
                      {description.length > APPROVAL_PREVIEW_LIMIT && (
                        <button
                          type="button"
                          onClick={() => setExpandedApproval((prev) => ({ ...prev, [`${expandKey}:desc`]: !descExpanded }))}
                          className="ml-1 text-[var(--color-accent)] hover:underline"
                        >
                          {descExpanded ? '收起' : '展开'}
                        </button>
                      )}
                    </p>
                  )}
                  {isNote ? (
                    <>
                      {title !== '' && (
                        <div className="flex gap-2">
                          <span className="shrink-0 text-[var(--color-text-tertiary)]">标题：</span>
                          <span className="font-medium text-[var(--color-text)]">{title}</span>
                        </div>
                      )}
                      {content !== '' && (
                        <div>
                          <div className="text-[var(--color-text-tertiary)]">正文预览：</div>
                          {expanded ? (
                            <div className={`prose prose-sm max-w-none markdown-body${theme === 'dark' ? ' prose-invert' : ''} max-h-96 overflow-y-auto pr-2`}>
                              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight, rehypeRaw]}>
                                {content}
                              </ReactMarkdown>
                            </div>
                          ) : (
                            <p className="whitespace-pre-wrap break-all text-[var(--color-text-secondary)]">
                              {truncateText(stripMarkdown(content), APPROVAL_PREVIEW_LIMIT)}
                            </p>
                          )}
                          {content.length > APPROVAL_PREVIEW_LIMIT && (
                            <button
                              type="button"
                              onClick={toggleExpanded}
                              className="mt-1 text-[var(--color-accent)] hover:underline"
                            >
                              {expanded ? '收起' : '展开全文'}
                            </button>
                          )}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="space-y-1">
                      {Object.entries(args).map(([k, v]) => (
                        <div key={k} className="flex gap-2">
                          <span className="shrink-0 text-[var(--color-text-tertiary)]">{k}：</span>
                          <span className="whitespace-pre-wrap break-all text-[var(--color-text-secondary)]">
                            {truncateText(typeof v === 'string' ? v : JSON.stringify(v), APPROVAL_ARG_LIMIT)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
            <div className="flex items-center gap-2">
              <button
                onClick={handleApprove}
                disabled={approveSubmitting}
                className="px-4 py-1.5 rounded-md bg-[var(--color-accent)] text-[var(--color-accent-contrast)] text-sm disabled:opacity-50"
              >
                同意
              </button>
              <button
                onClick={handleReject}
                disabled={approveSubmitting}
                className="px-4 py-1.5 rounded-md border border-[var(--color-border)] text-sm disabled:opacity-50"
              >
                拒绝
              </button>
              <input
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="拒绝原因（可选）"
                className="flex-1 min-w-0 px-3 py-1.5 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] text-xs"
              />
            </div>
          </div>
        </div>
      )}

      <div className="border-t border-[var(--color-border)] bg-[var(--color-card)] px-6 py-4">
        <div className="max-w-3xl mx-auto flex gap-3">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('chat.input')}
            rows={1}
            className="flex-1 resize-none rounded-[3px] border border-[var(--color-border)] bg-[var(--color-bg)] px-4 py-2.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-placeholder)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
          />
          <button
            onClick={() => handleSend(input)}
            disabled={!input.trim() || loading || approveSubmitting}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[3px] bg-[var(--color-accent)] text-[var(--color-accent-contrast)] hover:bg-[var(--color-accent-hover)] disabled:opacity-40"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
          </button>
        </div>
      </div>
    </div>
  )
}
