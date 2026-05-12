import { useState, useEffect } from 'react';
import { ShieldCheck, Check, X, Play, Clock, AlertTriangle, Search, RefreshCw, ChevronLeft, ChevronRight, Filter } from 'lucide-react';
import api from '../api/client';

interface CommandExecution {
  id: string;
  requested_by_email: string;
  alert_id: string | null;
  chat_session_id: string | null;
  target_type: string;
  target_server_id: string | null;
  target_server_name: string | null;
  command: string;
  description: string;
  risk_level: string;
  status: string;
  approved_by_email: string | null;
  approval_note: string | null;
  approved_at: string | null;
  executed_at: string | null;
  execution_result: Record<string, unknown>;
  execution_duration_ms: number | null;
  created_at: string;
  expires_at: string | null;
}

const statusColors: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-700',
  approved: 'bg-blue-100 text-blue-700',
  rejected: 'bg-red-100 text-red-700',
  executed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
  expired: 'bg-gray-100 text-gray-500',
};

const riskColors: Record<string, string> = {
  Low: 'bg-green-100 text-green-700',
  Medium: 'bg-amber-100 text-amber-700',
  High: 'bg-orange-100 text-orange-700',
  Critical: 'bg-red-100 text-red-700',
};

export default function CommandApprovalPage() {
  const [commands, setCommands] = useState<CommandExecution[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [pendingCount, setPendingCount] = useState(0);
  const [approvalModal, setApprovalModal] = useState<{ cmd: CommandExecution; action: 'approve' | 'reject' } | null>(null);
  const [approvalNote, setApprovalNote] = useState('');
  const [processing, setProcessing] = useState(false);
  const [detailCmd, setDetailCmd] = useState<CommandExecution | null>(null);
  const perPage = 15;

  const fetchCommands = async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page, per_page: perPage };
      if (statusFilter) params.status = statusFilter;
      const res = await api.get('/commands/', { params });
      setCommands(res.data.commands);
      setTotal(res.data.total);
    } catch { /* handled */ }
    setLoading(false);
  };

  const fetchPendingCount = async () => {
    try {
      const res = await api.get('/commands/pending/count');
      setPendingCount(res.data.pending_count);
    } catch { /* ignore */ }
  };

  useEffect(() => { fetchCommands(); }, [page, statusFilter]);
  useEffect(() => { fetchPendingCount(); }, []);

  const handleApproval = async () => {
    if (!approvalModal) return;
    setProcessing(true);
    try {
      await api.post(`/commands/${approvalModal.cmd.id}/approve`, {
        action: approvalModal.action,
        note: approvalNote.trim() || null,
      });
      setApprovalModal(null);
      setApprovalNote('');
      fetchCommands();
      fetchPendingCount();
    } catch { /* handled */ }
    setProcessing(false);
  };

  const totalPages = Math.max(1, Math.ceil(total / perPage));

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-800 flex items-center gap-3">
            <ShieldCheck className="h-6 w-6 text-brand-500" />
            Command Approvals
            {pendingCount > 0 && (
              <span className="text-sm bg-amber-100 text-amber-700 px-2.5 py-1 rounded-full font-semibold">
                {pendingCount} pending
              </span>
            )}
          </h2>
          <p className="text-sm text-gray-500 mt-1">Review and approve command execution requests</p>
        </div>
        <button onClick={() => { fetchCommands(); fetchPendingCount(); }} className="btn-secondary flex items-center gap-2">
          <RefreshCw className="h-4 w-4" /> Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4">
        <Filter className="h-4 w-4 text-gray-400" />
        {['', 'pending', 'approved', 'executed', 'rejected', 'failed', 'expired'].map(s => (
          <button
            key={s}
            onClick={() => { setPage(1); setStatusFilter(s); }}
            className={`text-xs px-3 py-1.5 rounded-full font-medium transition-colors ${
              statusFilter === s ? 'bg-brand-500 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {s || 'All'}
          </button>
        ))}
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex justify-center py-16">
          <div className="animate-spin h-8 w-8 border-4 border-brand-500 border-t-transparent rounded-full" />
        </div>
      ) : commands.length === 0 ? (
        <div className="card text-center py-16 text-gray-400">
          <Search className="h-10 w-10 mx-auto mb-3" />
          <p>No commands found</p>
        </div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Risk</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Requested By</th>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {commands.map(cmd => (
                <tr key={cmd.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <button
                      onClick={() => setDetailCmd(cmd)}
                      className="text-left hover:text-brand-600 font-medium max-w-xs truncate block"
                      title={cmd.description}
                    >
                      {cmd.description}
                    </button>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">{cmd.target_type.toUpperCase()}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${riskColors[cmd.risk_level] || 'bg-gray-100'}`}>
                      {cmd.risk_level}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${statusColors[cmd.status] || 'bg-gray-100'}`}>
                      {cmd.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{cmd.requested_by_email}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{new Date(cmd.created_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-right">
                    {cmd.status === 'pending' && (
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => { setApprovalNote(''); setApprovalModal({ cmd, action: 'approve' }); }}
                          className="p-1.5 rounded-md bg-green-100 text-green-700 hover:bg-green-200 transition-colors"
                          title="Approve"
                        >
                          <Check className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => { setApprovalNote(''); setApprovalModal({ cmd, action: 'reject' }); }}
                          className="p-1.5 rounded-md bg-red-100 text-red-700 hover:bg-red-200 transition-colors"
                          title="Reject"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      </div>
                    )}
                    {cmd.status === 'executed' && cmd.execution_duration_ms != null && (
                      <span className="text-xs text-gray-400">{cmd.execution_duration_ms}ms</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4 text-sm text-gray-500">
          <span>Page {page} of {totalPages} ({total} total)</span>
          <div className="flex gap-2">
            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="btn-secondary px-3 py-1.5 disabled:opacity-40">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)} className="btn-secondary px-3 py-1.5 disabled:opacity-40">
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* Approval modal */}
      {approvalModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg">
            <div className="px-6 py-5 space-y-4">
              <div className="flex items-center gap-3">
                <div className={`h-10 w-10 rounded-full flex items-center justify-center ${
                  approvalModal.action === 'approve' ? 'bg-green-100' : 'bg-red-100'
                }`}>
                  {approvalModal.action === 'approve' ? (
                    <Check className="h-5 w-5 text-green-600" />
                  ) : (
                    <X className="h-5 w-5 text-red-600" />
                  )}
                </div>
                <h3 className="text-base font-semibold text-gray-800">
                  {approvalModal.action === 'approve' ? 'Approve Command' : 'Reject Command'}
                </h3>
              </div>

              <div>
                <p className="text-sm text-gray-600 mb-2">{approvalModal.cmd.description}</p>
                <pre className="text-xs bg-gray-900 text-green-400 rounded-lg p-3 overflow-x-auto">
                  {approvalModal.cmd.command}
                </pre>
                <div className="flex gap-2 mt-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${riskColors[approvalModal.cmd.risk_level] || 'bg-gray-100'}`}>
                    {approvalModal.cmd.risk_level} Risk
                  </span>
                  <span className="text-xs text-gray-500">
                    Requested by {approvalModal.cmd.requested_by_email}
                  </span>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Note <span className="text-gray-400 font-normal">(optional)</span>
                </label>
                <textarea
                  rows={3}
                  className="input w-full resize-none text-sm"
                  placeholder={approvalModal.action === 'approve' ? 'Reason for approval...' : 'Reason for rejection...'}
                  value={approvalNote}
                  onChange={e => setApprovalNote(e.target.value)}
                  autoFocus
                />
              </div>

              {approvalModal.action === 'approve' && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-800">
                  <strong>Warning:</strong> Approving will immediately execute this command against the target system.
                </div>
              )}
            </div>
            <div className="flex justify-end gap-3 px-6 py-4 border-t border-gray-100">
              <button onClick={() => setApprovalModal(null)} className="btn-secondary" disabled={processing}>Cancel</button>
              <button
                onClick={handleApproval}
                disabled={processing}
                className={`px-4 py-2 rounded-lg text-white text-sm font-medium disabled:opacity-50 ${
                  approvalModal.action === 'approve' ? 'bg-green-600 hover:bg-green-700' : 'bg-red-600 hover:bg-red-700'
                }`}
              >
                {processing ? 'Processing...' : approvalModal.action === 'approve' ? 'Approve & Execute' : 'Reject'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Command detail modal */}
      {detailCmd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-xl max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 sticky top-0 bg-white">
              <h3 className="text-base font-semibold text-gray-800">Command Details</h3>
              <button onClick={() => setDetailCmd(null)} className="rounded-lg p-1 hover:bg-gray-100">
                <X className="h-5 w-5 text-gray-500" />
              </button>
            </div>
            <div className="px-6 py-5 space-y-4">
              <div>
                <h4 className="text-xs font-medium text-gray-500 uppercase mb-1">Description</h4>
                <p className="text-sm text-gray-800">{detailCmd.description}</p>
              </div>
              <div>
                <h4 className="text-xs font-medium text-gray-500 uppercase mb-1">Command</h4>
                <pre className="text-xs bg-gray-900 text-green-400 rounded-lg p-3 overflow-x-auto">{detailCmd.command}</pre>
              </div>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Type:</span>{' '}
                  <span className="font-medium">{detailCmd.target_type.toUpperCase()}</span>
                </div>
                <div>
                  <span className="text-gray-500">Risk:</span>{' '}
                  <span className={`text-xs px-2 py-0.5 rounded-full ${riskColors[detailCmd.risk_level] || ''}`}>{detailCmd.risk_level}</span>
                </div>
                <div>
                  <span className="text-gray-500">Status:</span>{' '}
                  <span className={`text-xs px-2 py-0.5 rounded-full ${statusColors[detailCmd.status] || ''}`}>{detailCmd.status}</span>
                </div>
                <div>
                  <span className="text-gray-500">Requested:</span>{' '}
                  <span className="text-gray-700">{new Date(detailCmd.created_at).toLocaleString()}</span>
                </div>
                <div>
                  <span className="text-gray-500">Requester:</span>{' '}
                  <span className="text-gray-700">{detailCmd.requested_by_email}</span>
                </div>
                {detailCmd.target_server_name && (
                  <div>
                    <span className="text-gray-500">Target:</span>{' '}
                    <span className="text-gray-700">{detailCmd.target_server_name}</span>
                  </div>
                )}
                {detailCmd.approved_by_email && (
                  <div>
                    <span className="text-gray-500">Approved By:</span>{' '}
                    <span className="text-gray-700">{detailCmd.approved_by_email}</span>
                  </div>
                )}
                {detailCmd.approved_at && (
                  <div>
                    <span className="text-gray-500">Approved At:</span>{' '}
                    <span className="text-gray-700">{new Date(detailCmd.approved_at).toLocaleString()}</span>
                  </div>
                )}
              </div>
              {detailCmd.approval_note && (
                <div>
                  <h4 className="text-xs font-medium text-gray-500 uppercase mb-1">Approval Note</h4>
                  <p className="text-sm text-gray-700 bg-gray-50 rounded-lg p-3">{detailCmd.approval_note}</p>
                </div>
              )}
              {detailCmd.execution_result && Object.keys(detailCmd.execution_result).length > 0 && (
                <div>
                  <h4 className="text-xs font-medium text-gray-500 uppercase mb-1">Execution Result</h4>
                  <pre className="text-xs bg-gray-900 text-gray-300 rounded-lg p-3 overflow-x-auto max-h-48">
                    {JSON.stringify(detailCmd.execution_result, null, 2)}
                  </pre>
                  {detailCmd.execution_duration_ms != null && (
                    <p className="text-xs text-gray-400 mt-1">Duration: {detailCmd.execution_duration_ms}ms</p>
                  )}
                </div>
              )}
              {detailCmd.status === 'pending' && (
                <div className="flex gap-2 pt-2">
                  <button
                    onClick={() => { setDetailCmd(null); setApprovalNote(''); setApprovalModal({ cmd: detailCmd, action: 'approve' }); }}
                    className="btn-primary flex items-center gap-2"
                  >
                    <Check className="h-4 w-4" /> Approve
                  </button>
                  <button
                    onClick={() => { setDetailCmd(null); setApprovalNote(''); setApprovalModal({ cmd: detailCmd, action: 'reject' }); }}
                    className="btn-secondary text-red-600 border-red-300 hover:bg-red-50 flex items-center gap-2"
                  >
                    <X className="h-4 w-4" /> Reject
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
