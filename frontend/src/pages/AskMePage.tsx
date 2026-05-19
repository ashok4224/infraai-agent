import { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  MessageSquare, Send, Plus, Trash2, Loader2, AlertTriangle, Database,
  Terminal, ShieldCheck, XCircle, Copy, Check, CheckCircle,
  ChevronDown, ChevronRight, Zap, X,
} from 'lucide-react';
import api from '../api/client';

function generateUUID(): string {
  const fn = (crypto as { randomUUID?: () => string }).randomUUID;
  if (typeof fn === 'function') return fn.call(crypto);
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

interface ToolOutput {
  type: 'table' | 'text' | 'json';
  columns?: string[];
  rows?: (string | number | null)[][];
  row_count?: number;
  truncated?: boolean;
  content?: string;
  data?: unknown;
}

interface ToolCallItem {
  type: string;
  server_name: string;
  query?: string;
  command?: string;
  description: string;
}

interface ToolPlan {
  id: string;
  explanation: string;
  calls: ToolCallItem[];
  status: string;
}

interface ToolExecuted {
  type: string;
  server_name: string;
  success: boolean;
  description: string;
  output?: ToolOutput | null;
  query?: string;
  command?: string;
  error?: string;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  metadata_json?: {
    tool_plan?: ToolPlan;
    tools_executed?: ToolExecuted[];
    suggested_follow_ups?: string[];
    [key: string]: unknown;
  };
  created_at: string;
}

interface ChatSession {
  id: string;
  title: string | null;
  ai_mode: string;
  created_at: string;
  message_count: number;
}

// â”€â”€ Tool Result Panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function ToolResultPanel({ tool }: { tool: ToolExecuted }) {
  const isSmall =
    tool.output?.type === 'table' ? (tool.output.row_count ?? 0) <= 10 :
    tool.output?.type === 'text' ? (tool.output.content?.length ?? 0) < 500 : false;
  const [expanded, setExpanded] = useState(isSmall && tool.success);

  const icon = ['sql', 'postgres', 'mysql'].includes(tool.type)
    ? <Database className="h-3.5 w-3.5" />
    : <Terminal className="h-3.5 w-3.5" />;

  const hasExpandable = tool.success && !!tool.output;
  const preview = tool.query || tool.command;

  return (
    <div className={`rounded-lg border mb-2 overflow-hidden ${tool.success ? 'border-gray-200' : 'border-red-200'}`}>
      <div
        className={`flex items-center justify-between px-3 py-2 ${hasExpandable ? 'cursor-pointer' : ''} ${tool.success ? 'bg-gray-50 hover:bg-gray-100' : 'bg-red-50'}`}
        onClick={() => hasExpandable && setExpanded(e => !e)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className={tool.success ? 'text-blue-600' : 'text-red-500'}>{icon}</span>
          <span className="text-xs font-semibold text-gray-700">{tool.server_name}</span>
          {preview && (
            <span className="text-xs text-gray-400 font-mono truncate max-w-xs hidden sm:block">
              {preview.slice(0, 60)}{preview.length > 60 ? 'â€¦' : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {tool.success
            ? <CheckCircle className="h-3.5 w-3.5 text-green-500" />
            : <XCircle className="h-3.5 w-3.5 text-red-500" />}
          {hasExpandable && (expanded
            ? <ChevronDown className="h-3.5 w-3.5 text-gray-400" />
            : <ChevronRight className="h-3.5 w-3.5 text-gray-400" />)}
        </div>
      </div>

      {expanded && tool.success && tool.output && (
        <div className="border-t border-gray-200">
          {tool.output.type === 'table' && (
            <div className="overflow-x-auto max-h-64">
              <table className="w-full text-xs">
                <thead className="bg-gray-100 sticky top-0">
                  <tr>
                    {tool.output.columns?.map((col, i) => (
                      <th key={i} className="px-3 py-1.5 text-left font-medium text-gray-600 whitespace-nowrap border-r border-gray-200 last:border-0">{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(tool.output.rows?.length ?? 0) === 0 ? (
                    <tr><td colSpan={tool.output.columns?.length || 1} className="px-3 py-2 text-gray-400 text-center italic">Query returned 0 rows</td></tr>
                  ) : tool.output.rows?.map((row, ri) => (
                    <tr key={ri} className={ri % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                      {row.map((cell, ci) => (
                        <td key={ci} className="px-3 py-1 text-gray-700 font-mono whitespace-nowrap border-r border-gray-100 last:border-0">
                          {cell === null || cell === undefined ? <span className="text-gray-300">â€”</span> : String(cell)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {tool.output.truncated && (
                <div className="px-3 py-1.5 text-xs text-gray-400 bg-gray-50 border-t border-gray-200">
                  Showing 50 of {tool.output.row_count} rows
                </div>
              )}
            </div>
          )}
          {tool.output.type === 'text' && (
            <pre className="text-xs p-3 bg-gray-900 text-green-400 overflow-x-auto max-h-48 whitespace-pre-wrap">
              {tool.output.content}{tool.output.truncated ? '\nâ€¦ (truncated)' : ''}
            </pre>
          )}
          {tool.output.type === 'json' && (
            <pre className="text-xs p-3 bg-gray-900 text-blue-300 overflow-x-auto max-h-48">
              {JSON.stringify(tool.output.data, null, 2)}
            </pre>
          )}
        </div>
      )}

      {!tool.success && tool.error && (
        <div className="px-3 py-2 text-xs text-red-600 border-t border-red-200 bg-red-50">
          {tool.error}
        </div>
      )}
    </div>
  );
}

// â”€â”€ Main Page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
export default function AskMePage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const contextAlertId = searchParams.get('alertId');
  const contextAlertName = searchParams.get('alertName');
  const shouldAutoInvestigate = searchParams.get('autoInvestigate') === 'true';

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [pendingPlan, setPendingPlan] = useState<{ planId: string; calls: ToolCallItem[]; explanation: string; sessionId: string } | null>(null);
  const [executing, setExecuting] = useState(false);
  const [copiedBlock, setCopiedBlock] = useState<string | null>(null);
  const [autoTriggered, setAutoTriggered] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, pendingPlan, scrollToBottom]);

  useEffect(() => {
    api.get('/chat/sessions').then(r => {
      setSessions(r.data);
      setLoadingSessions(false);
    }).catch(() => setLoadingSessions(false));
  }, []);

  useEffect(() => {
    if (!activeSessionId) { setMessages([]); setPendingPlan(null); return; }
    api.get(`/chat/sessions/${activeSessionId}`).then(r => {
      setMessages(r.data.messages || []);
      setPendingPlan(null);
    }).catch(() => setMessages([]));
  }, [activeSessionId]);

  // Auto-investigate when opened from Alert Detail with autoInvestigate=true
  useEffect(() => {
    if (shouldAutoInvestigate && contextAlertId && contextAlertName && !autoTriggered && !sending) {
      setAutoTriggered(true);
      const msg = `Investigate this alert and tell me the root cause and recommended fix: "${contextAlertName}"`;
      doSendMessage(msg, true);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shouldAutoInvestigate, contextAlertId, contextAlertName, autoTriggered]);

  // ── SSE streaming helper ──────────────────────────────────────────────────
  const streamSseChat = async (
    body: Record<string, unknown>,
    streamMsgId: string,
    onToolPlan: (plan: ToolPlan, sessionId: string) => void,
    onDone: (sessionId: string, messageId: string, metadataJson: ChatMessage['metadata_json']) => void,
  ) => {
    const token = localStorage.getItem('token');
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(errText || `HTTP ${response.status}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let accText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? '';

      for (const part of parts) {
        if (!part.trim()) continue;
        let eventType = 'message';
        let dataStr = '';
        for (const line of part.split('\n')) {
          if (line.startsWith('event: ')) eventType = line.slice(7).trim();
          if (line.startsWith('data: ')) dataStr = line.slice(6).trim();
        }
        if (!dataStr) continue;
        let payload: Record<string, unknown>;
        try { payload = JSON.parse(dataStr); } catch { continue; }

        if (eventType === 'token' && typeof payload.text === 'string') {
          accText += payload.text;
          setMessages(prev => prev.map(m =>
            m.id === streamMsgId ? { ...m, content: accText } : m
          ));
          setSending(false); // hide spinner once first token arrives
        } else if (eventType === 'tool_running') {
          const { index, total, description, type: tType, server_name } = payload as Record<string, unknown>;
          setMessages(prev => prev.map(m =>
            m.id === streamMsgId
              ? { ...m, content: `🔍 Diagnostic ${Number(index) + 1}/${total} — ${tType} on ${server_name}: ${description}` }
              : m
          ));
        } else if (eventType === 'tool_done') {
          // tool_done events are informational; synthesis tokens follow
        } else if (eventType === 'tool_plan') {
          const plan = payload.plan as ToolPlan;
          const sid = (payload.session_id as string) || '';
          // Remove the placeholder streaming message — plan card replaces it
          setMessages(prev => prev.filter(m => m.id !== streamMsgId));
          onToolPlan(plan, sid);
        } else if (eventType === 'done') {
          const { session_id, message_id, metadata_json } = payload as {
            session_id: string; message_id: string; metadata_json: ChatMessage['metadata_json'];
          };
          setMessages(prev => prev.map(m =>
            m.id === streamMsgId
              ? { ...m, id: message_id || streamMsgId, content: accText || m.content, metadata_json: metadata_json ?? {} }
              : m
          ));
          setStreamingId(null);
          onDone(session_id, message_id, metadata_json);
        } else if (eventType === 'error') {
          const msg = (payload.message as string) || 'Unknown error';
          setMessages(prev => prev.map(m =>
            m.id === streamMsgId ? { ...m, content: `Error: ${msg}` } : m
          ));
          setStreamingId(null);
          throw new Error(msg);
        }
      }
    }
  };

  const doSendMessage = async (text: string, autoInv = false) => {
    if (!text.trim() || sending) return;
    setSending(true);
    setPendingPlan(null);

    const userMsgId = generateUUID();
    const streamMsgId = generateUUID();
    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user', content: text, created_at: new Date().toISOString() },
      { id: streamMsgId, role: 'assistant', content: '', created_at: new Date().toISOString() },
    ]);
    setStreamingId(streamMsgId);

    try {
      await streamSseChat(
        {
          session_id: activeSessionId,
          message: text,
          context_alert_id: contextAlertId || undefined,
          auto_investigate: autoInv,
        },
        streamMsgId,
        (plan, sid) => {
          if (sid && sid !== activeSessionId) setActiveSessionId(sid);
          setPendingPlan({ planId: plan.id, calls: plan.calls, explanation: plan.explanation, sessionId: sid || activeSessionId || '' });
        },
        async (sessionId) => {
          if (sessionId && sessionId !== activeSessionId) {
            setActiveSessionId(sessionId);
            const sessRes = await api.get('/chat/sessions');
            setSessions(sessRes.data);
          } else if (!activeSessionId) {
            const sessRes = await api.get('/chat/sessions');
            setSessions(sessRes.data);
            setActiveSessionId(sessionId);
          }
        },
      );
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to send message';
      setMessages(prev => prev.map(m =>
        m.id === streamMsgId ? { ...m, content: `Error: ${errorMsg}` } : m
      ));
      setStreamingId(null);
    } finally {
      setSending(false);
      setStreamingId(null);
    }
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text) return;
    setInput('');
    await doSendMessage(text, false);
  };

  const handleApprovePlan = async () => {
    if (!pendingPlan || executing) return;
    setExecuting(true);

    const streamMsgId = generateUUID();
    setMessages(prev => [
      ...prev,
      { id: streamMsgId, role: 'assistant', content: '', created_at: new Date().toISOString() },
    ]);
    setStreamingId(streamMsgId);
    setPendingPlan(null);

    try {
      await streamSseChat(
        {
          session_id: pendingPlan.sessionId,
          message: '(approved tool execution)',
          approve_tool_plan: true,
          tool_plan_id: pendingPlan.planId,
          context_alert_id: contextAlertId || undefined,
        },
        streamMsgId,
        () => { /* tool_plan during approval is unexpected, ignore */ },
        async () => { /* session already active */ },
      );
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Execution failed';
      setMessages(prev => prev.map(m =>
        m.id === streamMsgId ? { ...m, content: `Error executing diagnostics: ${errorMsg}` } : m
      ));
      setStreamingId(null);
    } finally {
      setExecuting(false);
      setStreamingId(null);
    }
  };

  const handleRejectPlan = () => {
    setPendingPlan(null);
    setMessages(prev => [
      ...prev,
      { id: generateUUID(), role: 'assistant', content: "Okay, I won't run those diagnostics. Feel free to ask anything else.", created_at: new Date().toISOString() },
    ]);
  };

  const newSession = () => {
    setActiveSessionId(null);
    setMessages([]);
    setInput('');
    setPendingPlan(null);
  };

  const deleteSession = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this conversation?')) return;
    await api.delete(`/chat/sessions/${id}`);
    setSessions(prev => prev.filter(s => s.id !== id));
    if (activeSessionId === id) newSession();
  };

  const handleCopyBlock = (code: string, blockKey: string) => {
    navigator.clipboard.writeText(code);
    setCopiedBlock(blockKey);
    setTimeout(() => setCopiedBlock(null), 2000);
  };

  const renderAssistantContent = (content: string, msg: ChatMessage) => {
    const nodes: React.ReactNode[] = [];

    // Tool execution panels (replace old pills)
    const toolsExecuted = msg.metadata_json?.tools_executed;
    if (toolsExecuted && toolsExecuted.length > 0) {
      nodes.push(
        <div key="tools" className="mb-3">
          {toolsExecuted.map((t, i) => <ToolResultPanel key={i} tool={t} />)}
        </div>
      );
    }

    // Parse code blocks
    const codeBlockRegex = /```(\w*)\n([\s\S]*?)```/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    let blockCount = 0;

    while ((match = codeBlockRegex.exec(content)) !== null) {
      if (match.index > lastIndex) {
        nodes.push(<span key={`text-${lastIndex}`}>{content.slice(lastIndex, match.index)}</span>);
      }
      const lang = match[1] || 'code';
      const code = match[2].trim();
      const blockKey = `${msg.id}-${blockCount}`;
      nodes.push(
        <div key={blockKey} className="my-2 rounded-lg overflow-hidden border border-gray-300">
          <div className="bg-gray-800 px-3 py-1.5 flex items-center justify-between">
            <span className="text-xs text-gray-400 font-mono">{lang}</span>
            <button
              onClick={() => handleCopyBlock(code, blockKey)}
              className="p-1 rounded hover:bg-white/10 text-gray-400 hover:text-white"
              title="Copy"
            >
              {copiedBlock === blockKey ? <Check className="h-3.5 w-3.5 text-green-400" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
          </div>
          <pre className="bg-gray-900 text-green-400 text-xs p-3 overflow-x-auto">{code}</pre>
        </div>
      );
      blockCount++;
      lastIndex = match.index + match[0].length;
    }

    if (lastIndex < content.length) {
      nodes.push(<span key={`text-${lastIndex}`}>{content.slice(lastIndex)}</span>);
    }

    // Suggested follow-up buttons
    const followUps = msg.metadata_json?.suggested_follow_ups;
    if (followUps && followUps.length > 0) {
      nodes.push(
        <div key="follow-ups" className="mt-3 pt-3 border-t border-gray-200 flex flex-wrap gap-2">
          <span className="text-xs text-gray-400 w-full mb-1">Suggested next steps:</span>
          {followUps.map((q, i) => (
            <button
              key={i}
              onClick={() => setInput(q)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-brand-50 text-brand-700 border border-brand-200 hover:bg-brand-100 transition-colors"
            >
              <Zap className="h-3 w-3" />
              {q}
            </button>
          ))}
        </div>
      );
    }

    return nodes.length > 0 ? nodes : content;
  };

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-4">
      {/* Session sidebar */}
      <div className="w-64 flex-shrink-0 flex flex-col bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="p-3 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Conversations</h2>
          <button
            onClick={newSession}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-brand-600 transition-colors"
            title="New conversation"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {loadingSessions ? (
            <div className="flex justify-center py-8"><Loader2 className="h-5 w-5 animate-spin text-gray-400" /></div>
          ) : sessions.length === 0 ? (
            <p className="text-xs text-gray-400 text-center py-8">No conversations yet</p>
          ) : (
            sessions.map(s => (
              <div
                key={s.id}
                onClick={() => setActiveSessionId(s.id)}
                className={`group flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer text-sm transition-colors ${
                  activeSessionId === s.id ? 'bg-brand-50 text-brand-700 font-medium' : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <MessageSquare className="h-3.5 w-3.5 flex-shrink-0" />
                  <span className="truncate">{s.title || 'New Chat'}</span>
                </div>
                <button
                  onClick={(e) => deleteSession(s.id, e)}
                  className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-500 transition-opacity"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Chat area */}
      <div className="flex-1 flex flex-col bg-white rounded-xl border border-gray-200 overflow-hidden">

        {/* Alert context banner */}
        {contextAlertId && contextAlertName && (
          <div className="flex items-center gap-2 px-4 py-2 bg-amber-50 border-b border-amber-200 flex-shrink-0">
            <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0" />
            <span className="text-sm text-amber-700 min-w-0">
              Investigating: <strong className="font-semibold">{decodeURIComponent(contextAlertName)}</strong>
            </span>
            <button
              onClick={() => navigate('/ask-me', { replace: true })}
              className="ml-auto p-1 hover:bg-amber-100 rounded text-amber-500 flex-shrink-0"
              title="Clear alert context"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-400">
              <AlertTriangle className="h-12 w-12 mb-3 text-gray-300" />
              <p className="text-lg font-medium">AskMe â€” SRE Assistant</p>
              <p className="text-sm mt-1">Ask about alerts, database issues, infrastructure, or general SRE topics.</p>
              <p className="text-xs mt-2 text-gray-300">I can run live diagnostics with your approval.</p>
              {contextAlertId && contextAlertName && (
                <button
                  onClick={() => doSendMessage(`Investigate this alert and tell me the root cause and recommended fix: "${decodeURIComponent(contextAlertName)}"`, true)}
                  disabled={sending}
                  className="mt-5 flex items-center gap-2 px-5 py-2.5 rounded-lg bg-brand-500 text-white text-sm font-medium hover:bg-brand-600 disabled:opacity-50 transition-colors"
                >
                  <Zap className="h-4 w-4" />
                  Auto-Investigate This Alert
                </button>
              )}
            </div>
          ) : (
            messages.map(msg => (
              <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
                    msg.role === 'user'
                      ? 'bg-brand-500 text-white rounded-br-md'
                      : 'bg-gray-100 text-gray-800 rounded-bl-md'
                  }`}
                >
                  {msg.role === 'assistant' ? (
                    <>
                      {renderAssistantContent(msg.content, msg)}
                      {streamingId === msg.id && (
                        <span className="inline-block w-2 h-4 bg-gray-500 ml-0.5 animate-pulse align-middle" />
                      )}
                    </>
                  ) : msg.content}
                </div>
              </div>
            ))
          )}

          {/* Tool Plan Approval Card */}
          {pendingPlan && !executing && (
            <div className="flex justify-start">
              <div className="max-w-[80%] rounded-2xl border-2 border-amber-300 bg-amber-50 px-5 py-4">
                <div className="flex items-center gap-2 mb-3">
                  <ShieldCheck className="h-5 w-5 text-amber-600" />
                  <span className="font-semibold text-sm text-amber-800">Diagnostics Plan â€” Approval Required</span>
                </div>
                <div className="space-y-2 mb-4">
                  {pendingPlan.calls.map((call, i) => (
                    <div key={i} className="flex items-start gap-2 bg-white rounded-lg px-3 py-2 border border-amber-200">
                      {['sql', 'postgres', 'mysql'].includes(call.type) ? (
                        <Database className="h-4 w-4 text-blue-500 mt-0.5 flex-shrink-0" />
                      ) : (
                        <Terminal className="h-4 w-4 text-green-600 mt-0.5 flex-shrink-0" />
                      )}
                      <div className="min-w-0">
                        <div className="text-xs font-medium text-gray-700">
                          {call.type.toUpperCase()} on <span className="text-brand-600">{call.server_name}</span>
                        </div>
                        <div className="text-xs text-gray-500 mt-0.5">{call.description}</div>
                        {call.query && (
                          <pre className="text-xs bg-gray-50 text-gray-600 mt-1 p-1.5 rounded overflow-x-auto">{call.query}</pre>
                        )}
                        {call.command && (
                          <pre className="text-xs bg-gray-50 text-gray-600 mt-1 p-1.5 rounded overflow-x-auto">{call.command}</pre>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleApprovePlan}
                    className="px-4 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-sm font-medium transition-colors flex items-center gap-1.5"
                  >
                    <ShieldCheck className="h-3.5 w-3.5" />
                    Approve & Execute
                  </button>
                  <button
                    onClick={handleRejectPlan}
                    className="px-4 py-1.5 rounded-lg bg-gray-200 hover:bg-gray-300 text-gray-700 text-sm font-medium transition-colors"
                  >
                    Skip
                  </button>
                </div>
              </div>
            </div>
          )}

          {executing && (
            <div className="flex justify-start">
              <div className="bg-amber-50 border border-amber-200 rounded-2xl rounded-bl-md px-4 py-3 flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin text-amber-600" />
                <span className="text-sm text-amber-700">Executing diagnostics â€” connecting to systems...</span>
              </div>
            </div>
          )}

          {sending && !streamingId && (
            <div className="flex justify-start">
              <div className="bg-gray-100 rounded-2xl rounded-bl-md px-4 py-3 flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin text-gray-500" />
                <span className="text-sm text-gray-500">
                  {shouldAutoInvestigate && !autoTriggered ? 'Auto-investigating…' : 'Thinking…'}
                </span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="border-t border-gray-200 p-4">
          <div className="flex items-end gap-3">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
              placeholder="Ask somethingâ€¦"
              rows={1}
              className="flex-1 resize-none rounded-xl border border-gray-300 px-4 py-3 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none"
              disabled={sending || executing}
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || sending || executing}
              className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-500 text-white hover:bg-brand-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

