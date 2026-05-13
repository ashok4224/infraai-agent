import { useEffect, useRef, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import api from '../api/client';
import { ArrowLeft, RotateCw, ShieldCheck, Terminal, Copy, Check, AlertTriangle, Info, Database, Server, Tag, Layers, Cpu, HardDrive, MemoryStick, Network, Container, MessageSquare, X, Trash2, XCircle, CheckCircle, Send, StickyNote, Play } from 'lucide-react';

interface FixCommand {
  type: string;
  description: string;
  command: string;
  risk_level: string;
  requires_approval: boolean;
}

interface Analysis {
  id: string;
  problem_statement?: string;
  root_cause: string;
  confidence_score: number;
  action_plan: string[];
  fix_commands: FixCommand[];
  prevention_steps: string;
  risk_level: string;
  ai_provider_used: string;
  ai_model_used: string;
  tools_called: any[];
  logs_collected: Record<string, any>;
  full_ai_response: Record<string, any>;
  analyzed_at: string;
}

interface AlertNote {
  id: string;
  alert_id: string;
  author: string;
  content: string;
  created_at: string;
}

interface Alert {
  id: string;
  alertname: string;
  severity: string;
  status: string;
  instance: string | null;
  summary: string | null;
  description: string | null;
  labels: Record<string, string>;
  annotations: Record<string, string>;
  analysis_status: string;
  source: string;
  alert_category: string | null;
  alert_metadata: Record<string, any>;
  matched_agent_name: string | null;
  dedup_count: number;
  received_at: string;
  resolved_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  closed_by: string | null;
  analysis: Analysis | null;
  notes: AlertNote[];
}

export default function AlertDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [alert, setAlert] = useState<Alert | null>(null);
  const [loading, setLoading] = useState(true);
  const [reanalyzing, setReanalyzing] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [showHintModal, setShowHintModal] = useState(false);
  const [analystHint, setAnalystHint] = useState('');
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [newNote, setNewNote] = useState('');
  const [submittingNote, setSubmittingNote] = useState(false);
  const [executingIndex, setExecutingIndex] = useState<number | null>(null);
  const [executeConfirm, setExecuteConfirm] = useState<{ index: number; cmd: FixCommand } | null>(null);
  const [executeResult, setExecuteResult] = useState<{ index: number; success: boolean; message: string; status: string } | null>(null);

  const handleCopy = (text: string, index: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const fetchAlert = () => {
    setLoading(true);
    api.get(`/alerts/${id}`).then((res) => setAlert(res.data)).finally(() => setLoading(false));
  };

  useEffect(() => { fetchAlert(); }, [id]);

  // Clean up any running poll interval when the component unmounts
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const handleReanalyze = async (hint?: string) => {
    setShowHintModal(false);
    setReanalyzing(true);
    try {
      await api.post(`/alerts/${id}/reanalyze`, { analyst_hint: hint?.trim() || null });
      // Poll for completion with a maximum of 60 attempts (~3 min)
      let attempts = 0;
      const poll = setInterval(async () => {
        pollRef.current = poll;
        attempts++;
        try {
          const res = await api.get(`/alerts/${id}`);
          if (res.data.analysis_status !== 'analyzing' && res.data.analysis_status !== 'pending') {
            setAlert(res.data);
            clearInterval(poll);
            pollRef.current = null;
            setReanalyzing(false);
          } else if (attempts >= 60) {
            clearInterval(poll);
            pollRef.current = null;
            setReanalyzing(false);
          }
        } catch {
          clearInterval(poll);
          pollRef.current = null;
          setReanalyzing(false);
        }
      }, 3000);
    } catch {
      setReanalyzing(false);
    }
  };

  const handleForceClose = async () => {
    try {
      const res = await api.post(`/alerts/${id}/close`);
      setAlert(res.data);
    } catch { /* handled by interceptor */ }
  };

  const handleAcknowledge = async () => {
    try {
      const res = await api.post(`/alerts/${id}/acknowledge`);
      setAlert(res.data);
    } catch { /* handled by interceptor */ }
  };

  const handleDelete = async () => {
    try {
      await api.delete(`/alerts/${id}`);
      navigate('/alerts');
    } catch { /* handled by interceptor */ }
  };

  const handleAddNote = async () => {
    if (!newNote.trim()) return;
    setSubmittingNote(true);
    try {
      const res = await api.post(`/alerts/${id}/notes`, { content: newNote.trim() });
      setAlert(prev => prev ? { ...prev, notes: [...(prev.notes || []), res.data] } : prev);
      setNewNote('');
    } catch { /* handled by interceptor */ }
    setSubmittingNote(false);
  };

  const handleDeleteNote = async (noteId: string) => {
    try {
      await api.delete(`/alerts/${id}/notes/${noteId}`);
      setAlert(prev => prev ? { ...prev, notes: (prev.notes || []).filter(n => n.id !== noteId) } : prev);
    } catch { /* handled by interceptor */ }
  };

  const handleExecuteCommand = async (cmd: FixCommand, index: number) => {
    setExecuteConfirm(null);
    setExecutingIndex(index);
    setExecuteResult(null);
    try {
      const res = await api.post('/commands/', {
        command: cmd.command,
        description: cmd.description,
        target_type: cmd.type === 'sql' ? 'sql' : 'os',
        risk_level: cmd.risk_level || 'Medium',
        alert_id: id,
      });
      const data = res.data;
      if (data.status === 'executed') {
        setExecuteResult({
          index,
          success: data.execution_result?.success ?? true,
          message: data.execution_result?.output || data.execution_result?.error || 'Command executed successfully',
          status: 'executed',
        });
      } else if (data.status === 'failed') {
        setExecuteResult({
          index,
          success: false,
          message: data.execution_result?.error || 'Command execution failed',
          status: 'failed',
        });
      } else {
        // pending approval
        setExecuteResult({
          index,
          success: true,
          message: `Command submitted for approval (${data.risk_level} risk). An operator will review it.`,
          status: 'pending',
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to submit command';
      setExecuteResult({ index, success: false, message: msg, status: 'error' });
    } finally {
      setExecutingIndex(null);
    }
  };

  if (loading) {
    return <div className="flex justify-center py-20"><div className="animate-spin h-8 w-8 border-4 border-brand-500 border-t-transparent rounded-full" /></div>;
  }

  if (!alert) return <p className="text-gray-500">Alert not found.</p>;

  const analysis = alert.analysis;
  const riskColor = {
    Critical: 'text-red-600 bg-red-50',
    High: 'text-orange-600 bg-orange-50',
    Medium: 'text-amber-600 bg-amber-50',
    Low: 'text-green-600 bg-green-50',
  }[analysis?.risk_level || ''] || 'text-gray-600 bg-gray-50';

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Link to="/alerts" className="rounded-lg p-2 hover:bg-gray-100"><ArrowLeft className="h-5 w-5" /></Link>
        <div className="flex-1">
          <h2 className="text-2xl font-bold text-gray-800">{alert.alertname}</h2>
          <p className="text-sm text-gray-500">{alert.instance || 'No instance'} · {alert.source}</p>
        </div>
        <div className="flex items-center gap-2">
          {/* Acknowledge */}
          {alert.status === 'firing' && !alert.acknowledged_at && (
            <button onClick={handleAcknowledge} className="btn-secondary flex items-center gap-1.5 text-sm" title="Acknowledge alert">
              <CheckCircle className="h-4 w-4 text-blue-500" /> Acknowledge
            </button>
          )}
          {/* Force Close */}
          {alert.status === 'firing' && (
            <button onClick={handleForceClose} className="btn-secondary flex items-center gap-1.5 text-sm text-amber-700 border-amber-300 hover:bg-amber-50" title="Force close alert">
              <XCircle className="h-4 w-4" /> Force Close
            </button>
          )}
          {/* Re-Analyze */}
          <button
            onClick={() => { setAnalystHint(''); setShowHintModal(true); }}
            disabled={reanalyzing}
            className="btn-primary flex items-center gap-2 disabled:opacity-50"
          >
            <RotateCw className={`h-4 w-4 ${reanalyzing ? 'animate-spin' : ''}`} />
            {reanalyzing ? 'Analyzing...' : 'Re-Analyze'}
          </button>
          {/* Delete */}
          <button onClick={() => setShowDeleteConfirm(true)} className="btn-secondary flex items-center gap-1.5 text-sm text-red-600 border-red-300 hover:bg-red-50" title="Delete alert">
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Delete confirmation modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm">
            <div className="px-6 py-5 space-y-3">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-full bg-red-100 flex items-center justify-center">
                  <Trash2 className="h-5 w-5 text-red-600" />
                </div>
                <h3 className="text-base font-semibold text-gray-800">Delete Alert</h3>
              </div>
              <p className="text-sm text-gray-600">This will permanently delete <strong>{alert.alertname}</strong> and all associated analysis, notes. This cannot be undone.</p>
            </div>
            <div className="flex justify-end gap-3 px-6 py-4 border-t border-gray-100">
              <button onClick={() => setShowDeleteConfirm(false)} className="btn-secondary">Cancel</button>
              <button onClick={handleDelete} className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700">Delete</button>
            </div>
          </div>
        </div>
      )}

      {/* Re-Analyze hint modal */}
      {showHintModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
              <div className="flex items-center gap-2">
                <MessageSquare className="h-5 w-5 text-brand-500" />
                <h3 className="text-base font-semibold text-gray-800">Re-Analyze with Guidance</h3>
              </div>
              <button onClick={() => setShowHintModal(false)} className="rounded-lg p-1 hover:bg-gray-100">
                <X className="h-5 w-5 text-gray-500" />
              </button>
            </div>
            <div className="px-6 py-5 space-y-4">
              <p className="text-sm text-gray-600">
                Optionally provide context to guide the AI. For example, clarify which specific
                object is affected, correct a mis-identification, or add information the alert
                description doesn't include.
              </p>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Analyst Guidance <span className="text-gray-400 font-normal">(optional)</span>
                </label>
                <textarea
                  rows={5}
                  className="input w-full resize-none text-sm"
                  placeholder={`e.g. "This alert is specifically about the APP_STS_TX_DATA tablespace (not SYSTEM). It hit 95% usage due to a large batch job that ran overnight. Focus remediation on that tablespace only."`}
                  value={analystHint}
                  onChange={(e) => setAnalystHint(e.target.value)}
                  autoFocus
                />
              </div>
              <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-800">
                <strong>Tip:</strong> Be specific — name exact tablespaces, databases, services, or error codes.
                The AI will treat your guidance as highest priority over its own assumptions.
              </div>
            </div>
            <div className="flex justify-end gap-3 px-6 py-4 border-t border-gray-100">
              <button onClick={() => setShowHintModal(false)} className="btn-secondary">Cancel</button>
              <button onClick={() => handleReanalyze()} className="btn-secondary flex items-center gap-2">
                <RotateCw className="h-4 w-4" />
                Analyze without guidance
              </button>
              <button
                onClick={() => handleReanalyze(analystHint)}
                className="btn-primary flex items-center gap-2"
              >
                <RotateCw className="h-4 w-4" />
                Analyze with guidance
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Execute command confirmation modal */}
      {executeConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-md">
            <div className="px-6 py-5 space-y-3">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-full bg-amber-100 flex items-center justify-center">
                  <AlertTriangle className="h-5 w-5 text-amber-600" />
                </div>
                <h3 className="text-base font-semibold text-gray-800">Execute Command</h3>
              </div>
              <p className="text-sm text-gray-600">
                This <strong>{executeConfirm.cmd.risk_level} risk</strong> command requires confirmation:
              </p>
              <pre className="text-xs bg-gray-900 text-green-400 rounded-lg p-3 overflow-x-auto">
                {executeConfirm.cmd.command}
              </pre>
              <p className="text-xs text-gray-500">
                {executeConfirm.cmd.requires_approval
                  ? 'This command will be submitted for operator approval before execution.'
                  : 'This command will be submitted for execution.'}
              </p>
            </div>
            <div className="flex justify-end gap-3 px-6 py-4 border-t border-gray-100">
              <button onClick={() => setExecuteConfirm(null)} className="btn-secondary">Cancel</button>
              <button
                onClick={() => handleExecuteCommand(executeConfirm.cmd, executeConfirm.index)}
                className="px-4 py-2 rounded-lg bg-amber-600 text-white text-sm font-medium hover:bg-amber-700"
              >
                Submit for Execution
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Left column — Alert info */}
        <div className="lg:col-span-1 space-y-6">
          <div className="card">
            <h3 className="font-semibold text-gray-700 mb-3">Alert Info</h3>
            <dl className="space-y-2 text-sm">
              <Row label="Severity"><SevBadge s={alert.severity} /></Row>
              <Row label="Status"><span className={`badge ${alert.status === 'firing' ? 'badge-critical' : 'badge-success'}`}>{alert.status}</span></Row>
              <Row label="Analysis"><span className={`badge ${analysisClass(alert.analysis_status)}`}>{alert.analysis_status}</span></Row>
              <Row label="Category"><span className="badge bg-indigo-50 text-indigo-700">{alert.alert_category || 'general'}</span></Row>
              <Row label="Source"><span className="text-gray-700">{alert.source}</span></Row>
              {alert.matched_agent_name && <Row label="Matched Agent"><span className="badge bg-brand-50 text-brand-700">{alert.matched_agent_name}</span></Row>}
              {alert.dedup_count > 1 && <Row label="Occurrences"><span className="font-semibold text-amber-600">{alert.dedup_count}x</span></Row>}
              <Row label="Received">{new Date(alert.received_at).toLocaleString()}</Row>
              {alert.resolved_at && <Row label="Resolved">{new Date(alert.resolved_at).toLocaleString()}</Row>}
              {alert.acknowledged_at && (
                <Row label="Acknowledged">
                  <span className="text-blue-600" title={alert.acknowledged_by || ''}>
                    {new Date(alert.acknowledged_at).toLocaleString()}
                  </span>
                </Row>
              )}
              {alert.closed_by && <Row label="Closed By"><span className="text-gray-700">{alert.closed_by}</span></Row>}
            </dl>
          </div>

          {/* Extracted context cards */}
          <AlertContextCards alert={alert} />

          {/* Master Agent extracted metadata */}
          {alert.alert_metadata && Object.keys(alert.alert_metadata).length > 0 && (
            <div className="card">
              <h3 className="font-semibold text-gray-700 mb-3 flex items-center gap-2">
                <Cpu className="h-4 w-4 text-brand-500" /> Extracted Metadata
              </h3>
              <dl className="space-y-1.5">
                {Object.entries(alert.alert_metadata).map(([key, value]) => (
                  <div key={key} className="flex items-start gap-2 text-sm">
                    <dt className="text-gray-500 min-w-[130px] font-mono text-xs">{key}</dt>
                    <dd className="font-medium text-gray-800 break-all">{String(value)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          {(alert.summary || alert.description) && (
            <div className="card space-y-3">
              {alert.summary && (
                <>
                  <h3 className="font-semibold text-gray-700">Summary</h3>
                  <p className="text-sm text-gray-600 leading-relaxed">{alert.summary}</p>
                </>
              )}
              {alert.description && (
                <>
                  {alert.summary && <hr className="border-gray-100" />}
                  <h3 className="font-semibold text-gray-700">Alert Details</h3>
                  <DescriptionText text={alert.description} />
                </>
              )}
            </div>
          )}

          <div className="card">
            <h3 className="font-semibold text-gray-700 mb-2">Labels</h3>
            <div className="flex flex-wrap gap-1">
              {Object.entries(alert.labels || {}).map(([k, v]) => (
                <span key={k} className="inline-block bg-gray-100 text-xs px-2 py-1 rounded">{k}={v}</span>
              ))}
            </div>
          </div>

          {/* Notes / Comments */}
          <div className="card">
            <h3 className="font-semibold text-gray-700 mb-3 flex items-center gap-2">
              <StickyNote className="h-4 w-4 text-amber-500" /> Notes
              {alert.notes && alert.notes.length > 0 && (
                <span className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded-full">{alert.notes.length}</span>
              )}
            </h3>
            {alert.notes && alert.notes.length > 0 ? (
              <div className="space-y-2 mb-3 max-h-60 overflow-y-auto">
                {alert.notes.map(n => (
                  <div key={n.id} className="bg-gray-50 rounded-lg px-3 py-2 text-sm group relative">
                    <p className="text-gray-800">{n.content}</p>
                    <div className="flex items-center justify-between mt-1 text-xs text-gray-400">
                      <span>{n.author}</span>
                      <span>{new Date(n.created_at).toLocaleString()}</span>
                    </div>
                    <button
                      onClick={() => handleDeleteNote(n.id)}
                      className="absolute top-2 right-2 p-1 rounded hover:bg-red-100 opacity-0 group-hover:opacity-100 transition-opacity"
                      title="Delete note"
                    >
                      <X className="h-3 w-3 text-red-400" />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-400 mb-3">No notes yet.</p>
            )}
            <div className="flex gap-2">
              <input
                className="input-field flex-1 text-sm"
                placeholder="Add a note…"
                value={newNote}
                onChange={e => setNewNote(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddNote()}
              />
              <button
                onClick={handleAddNote}
                disabled={submittingNote || !newNote.trim()}
                className="btn-primary px-3 py-2 disabled:opacity-40"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Right column — Analysis */}
        <div className="lg:col-span-2 space-y-6">
          {analysis ? (
            <>
              <div className="card">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold text-gray-800">AI Analysis</h3>
                  <div className="flex items-center gap-3 text-xs text-gray-500">
                    <span className={`badge ${riskColor}`}>{analysis.risk_level} Risk</span>
                    <span>Confidence: {analysis.confidence_score != null ? Math.round(analysis.confidence_score * 100) : 'N/A'}%</span>
                    <span>{analysis.ai_provider_used} / {analysis.ai_model_used}</span>
                  </div>
                </div>

                {/* What's Happening — plain-English problem statement */}
                {analysis.problem_statement && (
                  <div className="mb-5 rounded-xl bg-amber-50 border border-amber-200 p-4">
                    <div className="flex items-start gap-3">
                      <AlertTriangle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                      <div>
                        <h4 className="text-xs font-bold text-amber-700 mb-1.5 uppercase tracking-widest">What's Happening</h4>
                        <p className="text-sm text-amber-900 leading-relaxed">{analysis.problem_statement}</p>
                      </div>
                    </div>
                  </div>
                )}

                <div className="mb-4">
                  <div className="flex items-center gap-2 mb-2">
                    <Info className="h-4 w-4 text-blue-500 flex-shrink-0" />
                    <h4 className="text-sm font-semibold text-gray-700">Root Cause</h4>
                  </div>
                  <p className="text-sm text-gray-800 bg-blue-50 border border-blue-100 rounded-lg p-3 leading-relaxed">{analysis.root_cause}</p>
                </div>

                <div className="mb-4">
                  <h4 className="text-sm font-medium text-gray-500 mb-2">Action Plan</h4>
                  <ol className="space-y-2">
                    {(analysis.action_plan || []).map((step, i) => (
                      <li key={i} className="flex gap-3 text-sm">
                        <span className="flex-shrink-0 flex h-6 w-6 items-center justify-center rounded-full bg-brand-500 text-white text-xs font-bold">{i + 1}</span>
                        <span className="text-gray-700 pt-0.5">{step}</span>
                      </li>
                    ))}
                  </ol>
                </div>

                {analysis.fix_commands && analysis.fix_commands.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-sm font-medium text-gray-500 mb-2">Remediation Commands</h4>
                    <div className="space-y-3">
                      {analysis.fix_commands.map((cmd, i) => (
                        <div key={i} className="border border-gray-200 rounded-lg overflow-hidden">
                          <div className="bg-gray-50 px-3 py-2 border-b border-gray-200 flex justify-between items-center">
                            <div className="flex items-center gap-2">
                              <Terminal className="h-4 w-4 text-brand-500" />
                              <span className="text-sm font-medium text-gray-800">{cmd.description}</span>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className={`text-xs px-2 py-0.5 rounded-full ${(cmd.risk_level || '').toLowerCase() === 'high' || (cmd.risk_level || '').toLowerCase() === 'critical' ? 'bg-red-100 text-red-700' : 'bg-gray-200 text-gray-700'}`}>
                                {cmd.risk_level} Risk
                              </span>
                              {cmd.requires_approval && (
                                <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">Needs Approval</span>
                              )}
                            </div>
                          </div>
                          <div className="bg-gray-900 p-3 relative group">
                            <pre className="text-xs text-green-400 overflow-x-auto pr-20">
                              {cmd.command}
                            </pre>
                            <div className="absolute top-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button 
                                onClick={() => handleCopy(cmd.command, i)}
                                className="p-1.5 rounded-md bg-white/10 hover:bg-white/20 text-white"
                                title="Copy command"
                              >
                                {copiedIndex === i ? <Check className="h-4 w-4 text-green-400" /> : <Copy className="h-4 w-4" />}
                              </button>
                              <button
                                onClick={() => {
                                  if (cmd.requires_approval || ['High', 'Critical'].includes(cmd.risk_level)) {
                                    setExecuteConfirm({ index: i, cmd });
                                  } else {
                                    handleExecuteCommand(cmd, i);
                                  }
                                }}
                                disabled={executingIndex === i}
                                className="p-1.5 rounded-md bg-green-600/80 hover:bg-green-600 text-white disabled:opacity-50"
                                title="Execute command"
                              >
                                {executingIndex === i ? <RotateCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                              </button>
                            </div>
                          </div>
                          {/* Execution result inline */}
                          {executeResult && executeResult.index === i && (
                            <div className={`px-3 py-2 text-xs border-t ${
                              executeResult.status === 'pending' ? 'bg-amber-50 text-amber-800 border-amber-200' :
                              executeResult.success ? 'bg-green-50 text-green-800 border-green-200' :
                              'bg-red-50 text-red-800 border-red-200'
                            }`}>
                              <div className="flex items-center gap-2">
                                {executeResult.status === 'pending' ? (
                                  <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
                                ) : executeResult.success ? (
                                  <CheckCircle className="h-3.5 w-3.5 flex-shrink-0" />
                                ) : (
                                  <XCircle className="h-3.5 w-3.5 flex-shrink-0" />
                                )}
                                <span className="font-medium">
                                  {executeResult.status === 'pending' ? 'Pending Approval' :
                                   executeResult.success ? 'Executed' : 'Failed'}
                                </span>
                              </div>
                              <pre className="mt-1 whitespace-pre-wrap break-all">{executeResult.message}</pre>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <h4 className="text-sm font-medium text-gray-500 mb-1">Prevention</h4>
                  <p className="text-sm text-gray-700 bg-green-50 rounded-lg p-3">{analysis.prevention_steps}</p>
                </div>
              </div>

              {/* Tools & Logs */}
              {(analysis.tools_called || []).length > 0 && (
                <div className="card">
                  <h3 className="font-semibold text-gray-700 mb-3">Tools Called</h3>
                  <div className="space-y-2">
                    {(analysis.tools_called || []).map((t: any, i: number) => (
                      <div key={i} className="flex items-center gap-2 text-sm bg-gray-50 px-3 py-2 rounded">
                        <ShieldCheck className="h-4 w-4 text-brand-500" />
                        <span className="font-medium">{t.tool}</span>
                        <span className="text-gray-500">on {t.server}</span>
                        <span className="text-gray-400">({t.query})</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {Object.keys(analysis.logs_collected || {}).length > 0 && (
                <div className="card">
                  <h3 className="font-semibold text-gray-700 mb-3">Collected Logs</h3>
                  <pre className="text-xs bg-gray-900 text-green-400 rounded-lg p-4 overflow-x-auto max-h-80">
                    {JSON.stringify(analysis.logs_collected, null, 2)}
                  </pre>
                </div>
              )}

              <div className="card">
                <h3 className="font-semibold text-gray-700 mb-3">Raw Webhook Payload</h3>
                <pre className="text-xs bg-gray-900 text-gray-300 rounded-lg p-4 overflow-x-auto max-h-60">
                  {JSON.stringify(alert.annotations, null, 2)}
                </pre>
              </div>
            </>
          ) : (
            <div className="card text-center py-12">
              {alert.analysis_status === 'analyzing' || alert.analysis_status === 'pending' ? (
                <>
                  <div className="animate-spin h-8 w-8 border-4 border-brand-500 border-t-transparent rounded-full mx-auto mb-4" />
                  <p className="text-gray-500">Analysis in progress...</p>
                </>
              ) : (
                <p className="text-gray-400">No analysis available. Click Re-Analyze to trigger.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DescriptionText({ text }: { text: string }) {
  // Highlight metric values inline: VALUE = X, percentages, storage sizes, thresholds
  const TOKEN_RE = /(\bVALUE\s*=\s*[\d.]+(?:\s*[A-Za-z]+)?|[<>]=?\s*\d+(?:\.\d+)?\s*(?:GB|MB|KB|TB|%)?|\b\d+(?:\.\d+)?\s*(?:GB|MB|KB|TB|%)\b)/g;
  const parts: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  TOKEN_RE.lastIndex = 0;
  while ((m = TOKEN_RE.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push(
      <mark key={m.index} className="bg-amber-100 text-amber-900 px-0.5 rounded font-semibold not-italic">
        {m[0]}
      </mark>
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <p className="text-sm text-gray-700 leading-relaxed font-mono">{parts}</p>;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between">
      <dt className="text-gray-500">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function SevBadge({ s }: { s: string }) {
  const c = { critical: 'badge-critical', warning: 'badge-warning', info: 'badge-info' }[s] || 'badge-info';
  return <span className={`badge ${c}`}>{s}</span>;
}

function analysisClass(s: string) {
  return { analyzed: 'badge-success', analyzing: 'badge-info', pending: 'badge-warning', failed: 'badge-critical' }[s] || 'badge-warning';
}

/* ── Intelligent context extraction ──────────────────────────────────────── */

interface Insight { icon: React.ReactNode; label: string; value: string }

function extractInsights(alert: Alert): Insight[] {
  const insights: Insight[] = [];
  const lbl = alert.labels || {};
  const ann = alert.annotations || {};
  const desc = (alert.description || '') + ' ' + (alert.summary || '');
  const aiResp = alert.analysis?.full_ai_response || {};
  const allText = desc + ' ' + JSON.stringify(lbl);
  const category = (alert.alert_category || 'general').toLowerCase();

  // Helper: first non-empty value from label keys
  const pick = (...keys: string[]) => { for (const k of keys) { if (lbl[k]) return lbl[k]; } return null; };

  // ────────────────────────────────────────────────── Common across all types

  // Alert type / category
  const catDisplay: Record<string, string> = {
    oracle_db: 'Oracle Database', ebs: 'Oracle EBS', postgresql: 'PostgreSQL',
    mysql: 'MySQL / MariaDB', sqlserver: 'SQL Server', linux_os: 'Linux OS',
    infrastructure: 'Infrastructure', general: 'General',
  };
  insights.push({ icon: <Tag className="h-4 w-4 text-indigo-500" />, label: 'Alert Type', value: catDisplay[category] || category });

  // Host / Instance
  const host = pick('host', 'instance', 'node', 'server', 'hostname', 'exported_instance') || alert.instance;
  if (host) insights.push({ icon: <Server className="h-4 w-4 text-slate-500" />, label: 'Host / Instance', value: host });

  // Job / Exporter
  const job = lbl['job'];
  if (job) insights.push({ icon: <Tag className="h-4 w-4 text-green-500" />, label: 'Job / Exporter', value: job });

  // ────────────────────────────────────────────────── Database common
  const dbName = pick('db', 'db_instance', 'database', 'dbname', 'oracle_sid', 'service_name',
    'pg_database', 'mysql_db', 'mssql_instance', 'sql_server_instance', 'datname', 'schema');
  if (dbName) insights.push({ icon: <Database className="h-4 w-4 text-blue-500" />, label: 'Database', value: dbName });

  // ────────────────────────────────────────────────── Oracle DB
  if (category === 'oracle_db' || category === 'ebs') {
    // Tablespace
    const ts = pick('tablespace', 'tablespace_name');
    const tsRx = !ts ? allText.match(/tablespace\s+(\w+)/i) : null;
    if (ts || tsRx) insights.push({ icon: <Layers className="h-4 w-4 text-purple-500" />, label: 'Tablespace', value: ts || tsRx![1] });

    // ORA- error code
    const oraMatch = allText.match(/ORA-\d{4,5}/i);
    if (oraMatch) insights.push({ icon: <AlertTriangle className="h-4 w-4 text-red-500" />, label: 'Error Code', value: oraMatch[0] });

    // ASM disk group
    const asmDg = pick('diskgroup', 'asm_diskgroup');
    const asmRx = !asmDg ? allText.match(/diskgroup\s+(\w+)/i) : null;
    if (asmDg || asmRx) insights.push({ icon: <HardDrive className="h-4 w-4 text-orange-500" />, label: 'ASM Disk Group', value: asmDg || asmRx![1] });

    // Data Guard role
    const dgRole = pick('dg_role', 'dataguard_role');
    if (dgRole) insights.push({ icon: <Tag className="h-4 w-4 text-teal-500" />, label: 'Data Guard Role', value: dgRole });

    // Archive log destination
    const archDest = pick('dest_id', 'log_archive_dest');
    if (archDest) insights.push({ icon: <Tag className="h-4 w-4 text-amber-600" />, label: 'Archive Dest', value: archDest });

    // EBS component
    const cmMatch = allText.match(/(?:concurrent\s+manager|FNDCPGSP|ICM|FNDLIBR|workflow|adop|autoconfig|adadmin)/i);
    if (cmMatch) insights.push({ icon: <Tag className="h-4 w-4 text-orange-500" />, label: 'EBS Component', value: cmMatch[0] });
  }

  // ────────────────────────────────────────────────── PostgreSQL
  if (category === 'postgresql') {
    // Schema / table
    const pgSchema = pick('schema', 'schemaname');
    if (pgSchema) insights.push({ icon: <Layers className="h-4 w-4 text-blue-400" />, label: 'Schema', value: pgSchema });

    const pgTable = pick('relname', 'table', 'table_name');
    if (pgTable) insights.push({ icon: <Layers className="h-4 w-4 text-blue-300" />, label: 'Table', value: pgTable });

    // Replication slot / state
    const repSlot = pick('slot_name', 'replication_slot');
    if (repSlot) insights.push({ icon: <Tag className="h-4 w-4 text-cyan-500" />, label: 'Replication Slot', value: repSlot });

    const repState = pick('state', 'replication_state');
    if (repState && /stream|catch|start|backup/i.test(repState))
      insights.push({ icon: <Tag className="h-4 w-4 text-cyan-600" />, label: 'Replication State', value: repState });

    // WAL / vacuum indicators from text
    const walMatch = allText.match(/WAL\s+size[:\s]+(\d[\d.\s]*[GMKT]B)/i);
    if (walMatch) insights.push({ icon: <HardDrive className="h-4 w-4 text-yellow-600" />, label: 'WAL Size', value: walMatch[1] });

    const deadTuples = allText.match(/dead.tuples?[:\s]+(\d[\d,]*)/i);
    if (deadTuples) insights.push({ icon: <Info className="h-4 w-4 text-amber-500" />, label: 'Dead Tuples', value: deadTuples[1] });

    // PG error / SQLSTATE
    const pgErr = allText.match(/(?:SQLSTATE|ERROR)\s*[:\s]*([A-Z0-9]{5})/i);
    if (pgErr) insights.push({ icon: <AlertTriangle className="h-4 w-4 text-red-500" />, label: 'Error / SQLSTATE', value: pgErr[0] });
  }

  // ────────────────────────────────────────────────── MySQL / MariaDB
  if (category === 'mysql') {
    const mysqlTable = pick('table', 'table_name', 'table_schema');
    if (mysqlTable) insights.push({ icon: <Layers className="h-4 w-4 text-blue-400" />, label: 'Table / Schema', value: mysqlTable });

    // InnoDB buffer pool hit ratio
    const bpMatch = allText.match(/buffer.pool.hit.ratio[:\s]+(\d[\d.]*%?)/i);
    if (bpMatch) insights.push({ icon: <Info className="h-4 w-4 text-amber-500" />, label: 'Buffer Pool Hit Ratio', value: bpMatch[1] });

    // Replication lag
    const repLag = pick('seconds_behind_master', 'replication_lag');
    const repLagRx = !repLag ? allText.match(/seconds.behind.master[:\s]+(\d+)/i) : null;
    if (repLag || repLagRx) insights.push({ icon: <Info className="h-4 w-4 text-orange-500" />, label: 'Replication Lag', value: (repLag || repLagRx![1]) + 's' });

    // Thread / connection count
    const threads = pick('threads_connected', 'threads_running');
    if (threads) insights.push({ icon: <Tag className="h-4 w-4 text-violet-500" />, label: 'Threads Connected', value: threads });

    // MySQL error code
    const mysqlErr = allText.match(/(?:ERROR|ER_)\s*(\d{4})/i);
    if (mysqlErr) insights.push({ icon: <AlertTriangle className="h-4 w-4 text-red-500" />, label: 'MySQL Error', value: mysqlErr[0] });
  }

  // ────────────────────────────────────────────────── SQL Server
  if (category === 'sqlserver') {
    const sqlDb = pick('database_name', 'db_name') || dbName;
    if (sqlDb && !dbName) insights.push({ icon: <Database className="h-4 w-4 text-blue-500" />, label: 'Database', value: sqlDb });

    // Availability Group
    const agMatch = allText.match(/availability.group\s*[\['"]*(\w[\w\s]*)/i);
    if (agMatch) insights.push({ icon: <Layers className="h-4 w-4 text-teal-500" />, label: 'Availability Group', value: agMatch[1].trim() });

    // TempDB related
    const tempMatch = allText.match(/tempdb/i);
    if (tempMatch) insights.push({ icon: <HardDrive className="h-4 w-4 text-amber-600" />, label: 'Subsystem', value: 'TempDB' });

    // SQL Agent job
    const agentJob = pick('job_name', 'sql_agent_job');
    const jobRx = !agentJob ? allText.match(/sql.agent.job[:\s]+['"]*(\w[\w\s]*)/i) : null;
    if (agentJob || jobRx) insights.push({ icon: <Tag className="h-4 w-4 text-orange-500" />, label: 'SQL Agent Job', value: agentJob || jobRx![1].trim() });

    // Wait type
    const waitType = pick('wait_type');
    const waitRx = !waitType ? allText.match(/(?:PAGELATCH|PAGEIOLATCH|LCK_M|CXPACKET|SOS_SCHEDULER)\w*/i) : null;
    if (waitType || waitRx) insights.push({ icon: <Info className="h-4 w-4 text-red-400" />, label: 'Wait Type', value: waitType || waitRx![0] });

    // SQL Server error
    const sqlErr = allText.match(/(?:Msg|Error)\s*(\d{3,5})/i);
    if (sqlErr) insights.push({ icon: <AlertTriangle className="h-4 w-4 text-red-500" />, label: 'SQL Error', value: sqlErr[0] });

    // Deadlock
    const dlMatch = allText.match(/deadlock/i);
    if (dlMatch) insights.push({ icon: <AlertTriangle className="h-4 w-4 text-red-600" />, label: 'Issue', value: 'Deadlock Detected' });
  }

  // ────────────────────────────────────────────────── Linux OS
  if (category === 'linux_os') {
    // Filesystem / mountpoint
    const mountpoint = pick('mountpoint', 'device', 'filesystem', 'fstype');
    if (mountpoint) insights.push({ icon: <HardDrive className="h-4 w-4 text-amber-600" />, label: 'Filesystem / Mount', value: mountpoint });

    // CPU metric
    const cpuMode = pick('mode', 'cpu');
    if (cpuMode && /idle|iowait|steal|system|user|irq|softirq/i.test(cpuMode))
      insights.push({ icon: <Cpu className="h-4 w-4 text-blue-500" />, label: 'CPU Mode', value: cpuMode });

    // Network interface
    const iface = pick('device', 'interface', 'nic');
    if (iface && /eth|ens|eno|bond|wlan|lo|br|veth/i.test(iface))
      insights.push({ icon: <Network className="h-4 w-4 text-sky-500" />, label: 'Network Interface', value: iface });

    // Systemd unit / service
    const unit = pick('name', 'systemd_unit', 'unit', 'service');
    if (unit && /\.service|\.timer|\.socket|\.mount/i.test(unit))
      insights.push({ icon: <Tag className="h-4 w-4 text-violet-500" />, label: 'Systemd Unit', value: unit });

    // OOM / kernel indicators
    const oomMatch = allText.match(/OOM|Out.of.Memory|oom.killer|oom_kill/i);
    if (oomMatch) insights.push({ icon: <MemoryStick className="h-4 w-4 text-red-600" />, label: 'Memory Issue', value: 'OOM Killer Triggered' });

    const kernelMatch = allText.match(/kernel\s+panic|soft\s+lockup|RCU\s+stall|segfault|BUG:/i);
    if (kernelMatch) insights.push({ icon: <AlertTriangle className="h-4 w-4 text-red-600" />, label: 'Kernel Issue', value: kernelMatch[0] });

    // Swap usage
    const swapMatch = allText.match(/swap\s+(?:usage|used)[:\s]+(\d[\d.]*\s*(?:GB|MB|%)?)/i);
    if (swapMatch) insights.push({ icon: <MemoryStick className="h-4 w-4 text-amber-500" />, label: 'Swap Usage', value: swapMatch[1] });

    // Load average
    const loadMatch = allText.match(/load.average[:\s]+(\d[\d.]*)/i);
    if (loadMatch) insights.push({ icon: <Cpu className="h-4 w-4 text-orange-500" />, label: 'Load Average', value: loadMatch[1] });

    // Inode usage
    const inodeMatch = allText.match(/inode[s]?\s+(?:usage|used)[:\s]+(\d[\d.]*%?)/i);
    if (inodeMatch) insights.push({ icon: <HardDrive className="h-4 w-4 text-yellow-600" />, label: 'Inode Usage', value: inodeMatch[1] });
  }

  // ────────────────────────────────────────────────── Infrastructure / Kubernetes
  if (category === 'infrastructure' || lbl['namespace'] || lbl['pod']) {
    const ns = pick('namespace', 'kubernetes_namespace');
    if (ns) insights.push({ icon: <Container className="h-4 w-4 text-cyan-500" />, label: 'Namespace', value: ns });

    const pod = pick('pod', 'pod_name');
    if (pod) insights.push({ icon: <Container className="h-4 w-4 text-cyan-600" />, label: 'Pod', value: pod });

    const container = pick('container', 'container_name');
    if (container) insights.push({ icon: <Container className="h-4 w-4 text-cyan-400" />, label: 'Container', value: container });

    const deployment = pick('deployment', 'daemonset', 'statefulset', 'replicaset');
    if (deployment) insights.push({ icon: <Layers className="h-4 w-4 text-sky-500" />, label: 'Workload', value: deployment });

    // CrashLoopBackOff / OOMKilled / Evicted
    const k8sIssue = allText.match(/CrashLoopBackOff|OOMKilled|ImagePullBackOff|Evicted|Pending|CreateContainerError/i);
    if (k8sIssue) insights.push({ icon: <AlertTriangle className="h-4 w-4 text-red-500" />, label: 'K8s Status', value: k8sIssue[0] });

    // Ingress / LB
    const ingress = pick('ingress', 'load_balancer', 'virtualservice');
    if (ingress) insights.push({ icon: <Network className="h-4 w-4 text-blue-400" />, label: 'Ingress / LB', value: ingress });

    // SSL / Certificate
    const sslMatch = allText.match(/certificate\s+(?:expires?|expiry|expiring)\s+(?:in\s+)?(\d+\s*days?)/i);
    if (sslMatch) insights.push({ icon: <Tag className="h-4 w-4 text-amber-500" />, label: 'Cert Expiry', value: sslMatch[1] });
  }

  // ────────────────────────────────────────────────── Generic (all categories)

  // Usage % (if not already shown by a category-specific match)
  const pctMatch = desc.match(/(\d+(?:\.\d+)?)\s*%/);
  if (pctMatch && !insights.some(i => i.label === 'Usage' || i.label === 'Inode Usage' || i.label === 'Swap Usage'))
    insights.push({ icon: <Info className="h-4 w-4 text-amber-500" />, label: 'Usage', value: pctMatch[0] });

  // Size / threshold
  const sizeMatch = desc.match(/(\d+(?:\.\d+)?)\s*(GB|MB|TB|KB)\b/i);
  if (sizeMatch && !insights.some(i => i.label === 'Size / Threshold' || i.label === 'WAL Size'))
    insights.push({ icon: <Info className="h-4 w-4 text-amber-500" />, label: 'Size / Threshold', value: sizeMatch[0] });

  // Service (fallback for non-OS categories)
  if (category !== 'linux_os') {
    const svc = pick('service', 'systemd_unit', 'unit');
    if (svc) insights.push({ icon: <Tag className="h-4 w-4 text-violet-500" />, label: 'Service', value: svc });
  }

  // Insights from AI full_ai_response
  if (aiResp.affected_object) insights.push({ icon: <Layers className="h-4 w-4 text-rose-500" />, label: 'Affected Object', value: String(aiResp.affected_object) });

  // MCP / diagnostic queries executed
  const toolCount = alert.analysis?.tools_called?.length ?? 0;
  if (toolCount > 0) insights.push({ icon: <Database className="h-4 w-4 text-emerald-500" />, label: 'Diagnostic Queries Run', value: String(toolCount) });

  return insights;
}

function AlertContextCards({ alert }: { alert: Alert }) {
  const insights = extractInsights(alert);
  if (insights.length === 0) return null;

  return (
    <div className="card">
      <h3 className="font-semibold text-gray-700 mb-3">Identified Context</h3>
      <dl className="space-y-2">
        {insights.map((ins, i) => (
          <div key={i} className="flex items-center gap-2 text-sm">
            {ins.icon}
            <dt className="text-gray-500 min-w-[110px]">{ins.label}</dt>
            <dd className="font-medium text-gray-800 truncate" title={ins.value}>{ins.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
