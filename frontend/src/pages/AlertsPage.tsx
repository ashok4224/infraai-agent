import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/client';
import { Search, Filter, ChevronLeft, ChevronRight, Trash2, XCircle, CheckCircle } from 'lucide-react';

interface Alert {
  id: string;
  alertname: string;
  severity: string;
  status: string;
  analysis_status: string;
  instance: string | null;
  summary: string | null;
  source: string;
  alert_category: string | null;
  received_at: string;
}

const CATEGORIES: { key: string; label: string; color: string }[] = [
  { key: '',             label: 'All',          color: 'bg-gray-100 text-gray-700' },
  { key: 'oracle_db',   label: '🗄 Oracle DB',   color: 'bg-red-50 text-red-700' },
  { key: 'ebs',         label: '🏢 EBS',         color: 'bg-orange-50 text-orange-700' },
  { key: 'postgresql',  label: '🐘 PostgreSQL',  color: 'bg-blue-50 text-blue-700' },
  { key: 'mysql',       label: '🐬 MySQL',       color: 'bg-teal-50 text-teal-700' },
  { key: 'sqlserver',   label: '🪟 SQL Server',  color: 'bg-purple-50 text-purple-700' },
  { key: 'linux_os',    label: '🐧 Linux OS',    color: 'bg-yellow-50 text-yellow-700' },
  { key: 'infrastructure', label: '🌐 Infra',   color: 'bg-indigo-50 text-indigo-700' },
  { key: 'general',     label: '📋 General',     color: 'bg-gray-50 text-gray-600' },
];

const CATEGORY_BADGE: Record<string, string> = {
  oracle_db: 'bg-red-50 text-red-700',
  ebs: 'bg-orange-50 text-orange-700',
  postgresql: 'bg-blue-50 text-blue-700',
  mysql: 'bg-teal-50 text-teal-700',
  sqlserver: 'bg-purple-50 text-purple-700',
  linux_os: 'bg-yellow-50 text-yellow-700',
  infrastructure: 'bg-indigo-50 text-indigo-700',
  general: 'bg-gray-100 text-gray-600',
};

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [perPage] = useState(20);
  const [search, setSearch] = useState('');
  const [severity, setSeverity] = useState('');
  const [status, setStatusFilter] = useState('');
  const [analysisStatus, setAnalysisStatus] = useState('');
  const [category, setCategory] = useState('');
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);

  const fetchAlerts = () => {
    setLoading(true);
    const params: Record<string, string | number> = { page, per_page: perPage };
    if (search) params.search = search;
    if (severity) params.severity = severity;
    if (status) params.status = status;
    if (analysisStatus) params.analysis_status = analysisStatus;
    if (category) params.category = category;
    api.get('/alerts/', { params })
      .then((res) => {
        setAlerts(res.data.alerts);
        setTotal(res.data.total);
        setSelected(new Set());
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchAlerts(); }, [page, severity, status, analysisStatus, category]);

  const totalPages = Math.ceil(total / perPage);

  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === alerts.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(alerts.map(a => a.id)));
    }
  };

  const bulkAction = async (action: 'close' | 'acknowledge' | 'delete') => {
    if (selected.size === 0) return;
    const ids = Array.from(selected);
    setBulkLoading(true);
    try {
      await api.post(`/alerts/bulk/${action}`, { alert_ids: ids });
      fetchAlerts();
    } catch { /* handled by interceptor */ }
    setBulkLoading(false);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold text-gray-800">Alerts</h2>
        <span className="text-sm text-gray-500">{total} total</span>
      </div>

      {/* Category tabs */}
      <div className="flex flex-wrap gap-1.5 mb-5">
        {CATEGORIES.map(c => (
          <button
            key={c.key}
            onClick={() => { setCategory(c.key); setPage(1); }}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all border ${
              category === c.key
                ? 'border-brand-500 bg-brand-500 text-white shadow-sm'
                : `${c.color} border-transparent hover:border-gray-300`
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="card mb-6">
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs font-medium text-gray-500 mb-1">Search</label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                className="input-field pl-9"
                placeholder="Search alert name..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && fetchAlerts()}
              />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Severity</label>
            <select className="input-field" value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1); }}>
              <option value="">All</option>
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Status</label>
            <select className="input-field" value={status} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}>
              <option value="">All</option>
              <option value="firing">Firing</option>
              <option value="resolved">Resolved</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Analysis</label>
            <select className="input-field" value={analysisStatus} onChange={(e) => { setAnalysisStatus(e.target.value); setPage(1); }}>
              <option value="">All</option>
              <option value="analyzed">Analyzed</option>
              <option value="analyzing">Analyzing</option>
              <option value="pending">Pending</option>
              <option value="failed">Failed</option>
            </select>
          </div>
          <button onClick={() => { setPage(1); fetchAlerts(); }} className="btn-primary flex items-center gap-1">
            <Filter className="h-4 w-4" /> Filter
          </button>
        </div>
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 mb-4 bg-brand-50 border border-brand-200 rounded-lg px-4 py-2.5">
          <span className="text-sm font-medium text-brand-700">{selected.size} selected</span>
          <div className="flex gap-2 ml-auto">
            <button
              onClick={() => bulkAction('acknowledge')}
              disabled={bulkLoading}
              className="btn-secondary text-xs flex items-center gap-1 py-1.5 px-3"
            >
              <CheckCircle className="h-3.5 w-3.5 text-blue-500" /> Acknowledge
            </button>
            <button
              onClick={() => bulkAction('close')}
              disabled={bulkLoading}
              className="btn-secondary text-xs flex items-center gap-1 py-1.5 px-3 text-amber-700 border-amber-300 hover:bg-amber-50"
            >
              <XCircle className="h-3.5 w-3.5" /> Force Close
            </button>
            <button
              onClick={() => { if (confirm(`Delete ${selected.size} alert(s)? This cannot be undone.`)) bulkAction('delete'); }}
              disabled={bulkLoading}
              className="btn-secondary text-xs flex items-center gap-1 py-1.5 px-3 text-red-600 border-red-300 hover:bg-red-50"
            >
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </button>
            <button onClick={() => setSelected(new Set())} className="text-xs text-gray-500 hover:text-gray-700 ml-2">Clear</button>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="card overflow-x-auto">
        {loading ? (
          <div className="flex justify-center py-12"><div className="animate-spin h-6 w-6 border-4 border-brand-500 border-t-transparent rounded-full" /></div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="py-3 px-2 w-8">
                  <input
                    type="checkbox"
                    checked={alerts.length > 0 && selected.size === alerts.length}
                    onChange={toggleAll}
                    className="rounded border-gray-300"
                  />
                </th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Alert Name</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Category</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Severity</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Status</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Analysis</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Instance</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Received</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((a) => (
                <tr key={a.id} className={`border-b border-gray-100 hover:bg-gray-50 cursor-pointer ${selected.has(a.id) ? 'bg-brand-50/50' : ''}`}>
                  <td className="py-3 px-2" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(a.id)}
                      onChange={() => toggleSelect(a.id)}
                      className="rounded border-gray-300"
                    />
                  </td>
                  <td className="py-3 px-2">
                    <Link to={`/alerts/${a.id}`} className="text-brand-500 hover:underline font-medium">{a.alertname}</Link>
                    {a.summary && <p className="text-xs text-gray-400 mt-0.5 truncate max-w-xs">{a.summary}</p>}
                  </td>
                  <td className="py-3 px-2">
                    {a.alert_category && (
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${CATEGORY_BADGE[a.alert_category] || 'bg-gray-100 text-gray-600'}`}>
                        {a.alert_category.replace('_', ' ')}
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-2"><SevBadge s={a.severity} /></td>
                  <td className="py-3 px-2">
                    <span className={`badge ${a.status === 'firing' ? 'badge-critical' : 'badge-success'}`}>{a.status}</span>
                  </td>
                  <td className="py-3 px-2"><AnalBadge s={a.analysis_status} /></td>
                  <td className="py-3 px-2 text-gray-600">{a.instance || '—'}</td>
                  <td className="py-3 px-2 text-gray-500 whitespace-nowrap">{new Date(a.received_at).toLocaleString()}</td>
                </tr>
              ))}
              {alerts.length === 0 && (
                <tr><td colSpan={8} className="text-center py-12 text-gray-400">No alerts found</td></tr>
              )}
            </tbody>
          </table>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between pt-4 border-t border-gray-200 mt-4">
            <p className="text-sm text-gray-500">Page {page} of {totalPages}</p>
            <div className="flex gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
                className="btn-secondary text-sm py-1.5 px-3 disabled:opacity-40 flex items-center gap-1"
              >
                <ChevronLeft className="h-4 w-4" /> Previous
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
                className="btn-secondary text-sm py-1.5 px-3 disabled:opacity-40 flex items-center gap-1"
              >
                Next <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SevBadge({ s }: { s: string }) {
  const c = { critical: 'badge-critical', warning: 'badge-warning', info: 'badge-info' }[s] || 'badge-info';
  return <span className={`badge ${c}`}>{s}</span>;
}
function AnalBadge({ s }: { s: string }) {
  const c = { analyzed: 'badge-success', analyzing: 'badge-info', pending: 'badge-warning', failed: 'badge-critical' }[s] || 'badge-warning';
  return <span className={`badge ${c}`}>{s}</span>;
}
