import { useState, useEffect, useRef, useCallback } from 'react';
import { MessageSquare, Send, Plus, Trash2, Loader2, AlertTriangle, Database, Terminal, ShieldCheck, XCircle, Copy, Check, CheckCircle } from 'lucide-react';
import api from '../api/client';

// Polyfill for crypto.randomUUID — not available on HTTP (non-secure) contexts
function generateUUID(): string {
  const fn = (crypto as { randomUUID?: () => string }).randomUUID;
  if (typeof fn === 'function') {
    return fn.call(crypto);
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

interface ToolCallItem {
  type: 'sql' | 'ssh';
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
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  metadata_json?: {
    tool_plan?: ToolPlan;
    tools_executed?: ToolExecuted[];
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

export default function AskMePage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [pendingPlan, setPendingPlan] = useState<{ planId: string; calls: ToolCallItem[]; explanation: string; sessionId: string } | null>(null);
  const [executing, setExecuting] = useState(false);
  const [copiedBlock, setCopiedBlock] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, pendingPlan, scrollToBottom]);

  // Load sessions on mount
  useEffect(() => {
    api.get('/chat/sessions').then(r => {
      setSessions(r.data);
      setLoadingSessions(false);
    }).catch(() => setLoadingSessions(false));
  }, []);

  // Load messages when session changes
  useEffect(() => {
    if (!activeSessionId) { setMessages([]); setPendingPlan(null); return; }
    api.get(`/chat/sessions/${activeSessionId}`).then(r => {
      setMessages(r.data.messages || []);
      setPendingPlan(null);
    }).catch(() => setMessages([]));
  }, [activeSessionId]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    setInput('');
    setPendingPlan(null);

    // Optimistic user bubble
    const tempMsg: ChatMessage = { id: 'temp', role: 'user', content: text, created_at: new Date().toISOString() };
    setMessages(prev => [...prev, tempMsg]);

    try {
      const res = await api.post('/chat/', { session_id: activeSessionId, message: text });
      const { session_id, message, tool_plan, metadata_json } = res.data;

      // If this was a new session, update state
      if (!activeSessionId || session_id !== activeSessionId) {
        setActiveSessionId(session_id);
        const sessRes = await api.get('/chat/sessions');
        setSessions(sessRes.data);
      }

      // Replace temp message + add assistant reply
      const assistantMsg: ChatMessage = {
        id: generateUUID(),
        role: 'assistant',
        content: message,
        metadata_json: metadata_json || {},
        created_at: new Date().toISOString(),
      };

      setMessages(prev => [
        ...prev.filter(m => m.id !== 'temp'),
        { ...tempMsg, id: generateUUID() },
        assistantMsg,
      ]);

      // If AI returned a tool plan, show approval card
      if (tool_plan && tool_plan.calls?.length > 0) {
        setPendingPlan({
          planId: tool_plan.id,
          calls: tool_plan.calls,
          explanation: tool_plan.explanation || message,
          sessionId: session_id,
        });
      }
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to send message';
      setMessages(prev => [
        ...prev.filter(m => m.id !== 'temp'),
        { ...tempMsg, id: generateUUID() },
        { id: 'err', role: 'assistant', content: `Error: ${errorMsg}`, created_at: new Date().toISOString() },
      ]);
    } finally {
      setSending(false);
    }
  };

  const handleApprovePlan = async () => {
    if (!pendingPlan || executing) return;
    setExecuting(true);

    try {
      const res = await api.post('/chat/', {
        session_id: pendingPlan.sessionId,
        message: '(approved tool execution)',
        approve_tool_plan: true,
        tool_plan_id: pendingPlan.planId,
      });

      const { message, metadata_json } = res.data;

      setMessages(prev => [
        ...prev,
        {
          id: generateUUID(),
          role: 'assistant',
          content: message,
          metadata_json: metadata_json || {},
          created_at: new Date().toISOString(),
        },
      ]);
      setPendingPlan(null);
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Execution failed';
      setMessages(prev => [
        ...prev,
        { id: 'exec-err', role: 'assistant', content: `Error executing diagnostics: ${errorMsg}`, created_at: new Date().toISOString() },
      ]);
    } finally {
      setExecuting(false);
    }
  };

  const handleRejectPlan = () => {
    setPendingPlan(null);
    setMessages(prev => [
      ...prev,
      { id: generateUUID(), role: 'assistant', content: 'Okay, I won\'t run those diagnostics. Feel free to ask anything else.', created_at: new Date().toISOString() },
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

  /** Render assistant message content with code blocks (copy only) and tool badges */
  const renderAssistantContent = (content: string, msg: ChatMessage) => {
    const nodes: React.ReactNode[] = [];

    // Tool execution badges
    const toolsExecuted = msg.metadata_json?.tools_executed;
    if (toolsExecuted && toolsExecuted.length > 0) {
      nodes.push(
        <div key="tools-badge" className="mb-3 flex flex-wrap gap-1.5">
          {toolsExecuted.map((t, i) => (
            <span
              key={i}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                t.success ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
              }`}
            >
              {t.type === 'sql' ? <Database className="h-3 w-3" /> : <Terminal className="h-3 w-3" />}
              {t.server_name}
              {t.success ? <CheckCircle className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
            </span>
          ))}
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
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-400">
              <AlertTriangle className="h-12 w-12 mb-3 text-gray-300" />
              <p className="text-lg font-medium">AskMe — SRE Assistant</p>
              <p className="text-sm mt-1">Ask about alerts, database issues, infrastructure, or general SRE topics.</p>
              <p className="text-xs mt-2 text-gray-300">I can run live diagnostics with your approval.</p>
            </div>
          ) : (
            messages.map(msg => (
              <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
                    msg.role === 'user'
                      ? 'bg-brand-500 text-white rounded-br-md'
                      : 'bg-gray-100 text-gray-800 rounded-bl-md'
                  }`}
                >
                  {msg.role === 'assistant' ? renderAssistantContent(msg.content, msg) : msg.content}
                </div>
              </div>
            ))
          )}

          {/* Tool Plan Approval Card */}
          {pendingPlan && !executing && (
            <div className="flex justify-start">
              <div className="max-w-[75%] rounded-2xl border-2 border-amber-300 bg-amber-50 px-5 py-4">
                <div className="flex items-center gap-2 mb-3">
                  <ShieldCheck className="h-5 w-5 text-amber-600" />
                  <span className="font-semibold text-sm text-amber-800">Diagnostics Plan — Approval Required</span>
                </div>
                <div className="space-y-2 mb-4">
                  {pendingPlan.calls.map((call, i) => (
                    <div key={i} className="flex items-start gap-2 bg-white rounded-lg px-3 py-2 border border-amber-200">
                      {call.type === 'sql' ? (
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

          {/* Executing spinner */}
          {executing && (
            <div className="flex justify-start">
              <div className="bg-amber-50 border border-amber-200 rounded-2xl rounded-bl-md px-4 py-3 flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin text-amber-600" />
                <span className="text-sm text-amber-700">Executing diagnostics — connecting to systems...</span>
              </div>
            </div>
          )}

          {/* Planning spinner */}
          {sending && (
            <div className="flex justify-start">
              <div className="bg-gray-100 rounded-2xl rounded-bl-md px-4 py-3 flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin text-gray-500" />
                <span className="text-sm text-gray-500">Thinking...</span>
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
              placeholder="Ask something..."
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
