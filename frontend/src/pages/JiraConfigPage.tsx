import { useEffect, useState } from 'react';
import api from '../api/client';
import { Plus, Pencil, Trash2, X, Check, HeartPulse, Eye, EyeOff, Ticket, BookOpen, Search } from 'lucide-react';

interface JiraServer {
  id: string;
  name: string;
  description: string | null;
  instance_type: string;
  base_url: string;
  auth_email: string | null;
  has_token: boolean;
  project_keys: string[];
  jsm_enabled: boolean;
  jsm_service_desk_id: string | null;
  kb_enabled: boolean;
  kb_space_keys: string[];
  max_results: number;
  issue_types_filter: string[];
  status_filter: string[];
  label_filter: string[];
  is_active: boolean;
  health_status: string;
  last_health_check: string | null;
  created_at: string;
}

export default function JiraConfigPage() {
  const [servers, setServers] = useState<JiraServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editServer, setEditServer] = useState<JiraServer | null>(null);
  const [checking, setChecking] = useState<string | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [testResult, setTestResult] = useState<{ status: string; error?: string; server_title?: string; version?: string } | null>(null);
  const [testing, setTesting] = useState(false);

  const emptyForm = {
    name: '', description: '', instance_type: 'cloud', base_url: '',
    auth_email: '', api_token: '',
    project_keys: '', jsm_enabled: false, jsm_service_desk_id: '',
    kb_enabled: false, kb_space_keys: '',
    max_results: 10, issue_types_filter: '', status_filter: '', label_filter: '',
    is_active: true,
  };
  const [form, setForm] = useState(emptyForm);

  const fetchServers = () => {
    setLoading(true);
    api.get('/jira-config/').then((res) => setServers(res.data)).finally(() => setLoading(false));
  };

  useEffect(() => { fetchServers(); }, []);

  const openCreate = () => {
    setEditServer(null);
    setForm(emptyForm);
    setTestResult(null);
    setShowModal(true);
  };

  const openEdit = (s: JiraServer) => {
    setEditServer(s);
    setForm({
      name: s.name,
      description: s.description || '',
      instance_type: s.instance_type,
      base_url: s.base_url,
      auth_email: s.auth_email || '',
      api_token: '',
      project_keys: (s.project_keys || []).join(', '),
      jsm_enabled: s.jsm_enabled,
      jsm_service_desk_id: s.jsm_service_desk_id || '',
      kb_enabled: s.kb_enabled,
      kb_space_keys: (s.kb_space_keys || []).join(', '),
      max_results: s.max_results,
      issue_types_filter: (s.issue_types_filter || []).join(', '),
      status_filter: (s.status_filter || []).join(', '),
      label_filter: (s.label_filter || []).join(', '),
      is_active: s.is_active,
    });
    setTestResult(null);
    setShowModal(true);
  };

  const parseCSV = (val: string): string[] => val ? val.split(',').map((s) => s.trim()).filter(Boolean) : [];

  const buildPayload = () => ({
    ...form,
    project_keys: parseCSV(form.project_keys),
    kb_space_keys: parseCSV(form.kb_space_keys),
    issue_types_filter: parseCSV(form.issue_types_filter),
    status_filter: parseCSV(form.status_filter),
    label_filter: parseCSV(form.label_filter),
    max_results: Number(form.max_results),
  });

  const handleSubmit = async () => {
    const data: any = buildPayload();
    if (editServer) {
      if (!data.api_token) delete data.api_token;
      await api.patch(`/jira-config/${editServer.id}`, data);
      setShowModal(false);
      fetchServers();
    } else {
      const res = await api.post('/jira-config/', data);
      setShowModal(false);
      fetchServers();
      if (res.data?.health && res.data.health.status !== 'healthy') {
        alert(`⚠️ Config saved, but Jira connectivity check failed:\n${res.data.health.error || 'Unknown error'}\n\nUpdate settings and re-test.`);
      }
    }
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const data = buildPayload();
      const res = await api.post('/jira-config/test-connection', data);
      setTestResult(res.data);
    } catch (err: any) {
      setTestResult({ status: 'unhealthy', error: err.response?.data?.detail || err.message });
    } finally {
      setTesting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this Jira configuration?')) return;
    await api.delete(`/jira-config/${id}`);
    fetchServers();
  };

  const handleHealthCheck = async (id: string) => {
    setChecking(id);
    try {
      await api.post(`/jira-config/${id}/health-check`);
      fetchServers();
    } finally {
      setChecking(null);
    }
  };

  const healthBadge = (status: string) => {
    const cls = { healthy: 'badge-success', unhealthy: 'badge-critical', unknown: 'badge-warning', unreachable: 'badge-critical' }[status] || 'badge-warning';
    return <span className={`badge ${cls}`}>{status}</span>;
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-lg font-semibold text-gray-800">Jira / Service Management</h3>
          <p className="text-sm text-gray-500 mt-1">Connect to Jira Software & JSM to leverage historical issues and knowledge base for AI analysis</p>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus className="h-4 w-4" /> Add Jira Connection
        </button>
      </div>

      <div className="grid gap-4">
        {loading ? (
          <div className="card flex justify-center py-12"><div className="animate-spin h-6 w-6 border-4 border-brand-500 border-t-transparent rounded-full" /></div>
        ) : servers.length === 0 ? (
          <div className="card text-center py-12">
            <Ticket className="h-10 w-10 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-400">No Jira connections configured</p>
            <p className="text-xs text-gray-400 mt-1">Add a Jira instance to enable historical issue search and knowledge base lookups during alert analysis</p>
          </div>
        ) : (
          servers.map((s) => (
            <div key={s.id} className="card">
              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-semibold text-gray-800">{s.name}</h3>
                    {healthBadge(s.health_status)}
                    <span className={`badge ${s.is_active ? 'badge-success' : 'bg-gray-100 text-gray-500'}`}>{s.is_active ? 'Active' : 'Inactive'}</span>
                    {s.jsm_enabled && <span className="badge bg-purple-50 text-purple-600">JSM</span>}
                    {s.kb_enabled && <span className="badge bg-blue-50 text-blue-600"><BookOpen className="h-3 w-3 inline mr-1" />KB</span>}
                  </div>
                  {s.description && <p className="text-sm text-gray-500 mb-2">{s.description}</p>}
                  <div className="text-sm text-gray-500 flex flex-wrap gap-x-4 gap-y-1">
                    <span>Type: <strong>{s.instance_type}</strong></span>
                    <span>URL: <a href={s.base_url} target="_blank" rel="noreferrer" className="text-brand-600 hover:underline">{s.base_url}</a></span>
                    {s.auth_email && <span>User: <strong>{s.auth_email}</strong></span>}
                  </div>
                  {s.project_keys.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {s.project_keys.map((k) => (
                        <span key={k} className="inline-block bg-brand-50 text-brand-600 text-xs px-2 py-0.5 rounded">{k}</span>
                      ))}
                    </div>
                  )}
                  {s.last_health_check && (
                    <p className="text-xs text-gray-400 mt-1">Last checked: {new Date(s.last_health_check).toLocaleString()}</p>
                  )}
                </div>
                <div className="flex gap-2">
                  <button onClick={() => handleHealthCheck(s.id)} disabled={checking === s.id} className="btn-accent text-sm py-1.5 px-3 flex items-center gap-1 disabled:opacity-50">
                    <HeartPulse className={`h-3.5 w-3.5 ${checking === s.id ? 'animate-pulse' : ''}`} /> Health
                  </button>
                  <button onClick={() => openEdit(s)} className="btn-secondary text-sm py-1.5 px-3 flex items-center gap-1">
                    <Pencil className="h-3.5 w-3.5" /> Edit
                  </button>
                  <button onClick={() => handleDelete(s.id)} className="btn-danger text-sm py-1.5 px-3 flex items-center gap-1">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowModal(false)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-xl p-6 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">{editServer ? 'Edit Jira Connection' : 'Add Jira Connection'}</h3>
              <button onClick={() => setShowModal(false)} className="p-1 rounded hover:bg-gray-100"><X className="h-5 w-5" /></button>
            </div>
            <div className="space-y-3">
              {/* Basic info */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                  <input className="input-field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="jira-prod" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Instance Type</label>
                  <select className="input-field" value={form.instance_type} onChange={(e) => setForm({ ...form, instance_type: e.target.value })}>
                    <option value="cloud">Cloud (Atlassian)</option>
                    <option value="server">Server / Data Center</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <input className="input-field" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Production Jira instance" />
              </div>

              {/* Connection */}
              <div className="border-t pt-3 mt-2">
                <p className="text-sm font-medium text-gray-700 mb-2">Connection</p>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Base URL</label>
                  <input className="input-field" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder={form.instance_type === 'cloud' ? 'https://yourorg.atlassian.net' : 'https://jira.yourcompany.com'} />
                </div>
                <div className="grid grid-cols-2 gap-3 mt-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">{form.instance_type === 'cloud' ? 'Email' : 'Username'}</label>
                    <input className="input-field" value={form.auth_email} onChange={(e) => setForm({ ...form, auth_email: e.target.value })} placeholder={form.instance_type === 'cloud' ? 'user@company.com' : 'admin'} />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">{form.instance_type === 'cloud' ? 'API Token' : 'Personal Access Token'} {editServer && '(blank = keep current)'}</label>
                    <div className="relative">
                      <input className="input-field pr-10" type={showToken ? 'text' : 'password'} value={form.api_token} onChange={(e) => setForm({ ...form, api_token: e.target.value })} />
                      <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2" onClick={() => setShowToken(!showToken)}>
                        {showToken ? <EyeOff className="h-4 w-4 text-gray-400" /> : <Eye className="h-4 w-4 text-gray-400" />}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* Project & Filtering */}
              <div className="border-t pt-3 mt-2">
                <p className="text-sm font-medium text-gray-700 mb-2">Search Scope</p>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Project Keys (comma-separated)</label>
                  <input className="input-field" value={form.project_keys} onChange={(e) => setForm({ ...form, project_keys: e.target.value })} placeholder="OPS, INFRA, INC" />
                </div>
                <div className="grid grid-cols-2 gap-3 mt-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Issue Types Filter</label>
                    <input className="input-field" value={form.issue_types_filter} onChange={(e) => setForm({ ...form, issue_types_filter: e.target.value })} placeholder="Bug, Incident, Problem" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Status Filter</label>
                    <input className="input-field" value={form.status_filter} onChange={(e) => setForm({ ...form, status_filter: e.target.value })} placeholder="Done, Resolved, Closed" />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3 mt-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Label Filter</label>
                    <input className="input-field" value={form.label_filter} onChange={(e) => setForm({ ...form, label_filter: e.target.value })} placeholder="production, critical" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Max Results per Search</label>
                    <input className="input-field" type="number" value={form.max_results} onChange={(e) => setForm({ ...form, max_results: Number(e.target.value) })} />
                  </div>
                </div>
              </div>

              {/* JSM & Knowledge Base */}
              <div className="border-t pt-3 mt-2">
                <p className="text-sm font-medium text-gray-700 mb-2">Service Management & Knowledge Base</p>
                <label className="flex items-center gap-2 mb-3">
                  <input type="checkbox" className="rounded border-gray-300" checked={form.jsm_enabled} onChange={(e) => setForm({ ...form, jsm_enabled: e.target.checked })} />
                  <span className="text-sm text-gray-700">Enable JSM (Jira Service Management) integration</span>
                </label>
                {form.jsm_enabled && (
                  <div className="mb-3">
                    <label className="block text-xs text-gray-500 mb-1">Service Desk ID</label>
                    <input className="input-field" value={form.jsm_service_desk_id} onChange={(e) => setForm({ ...form, jsm_service_desk_id: e.target.value })} placeholder="1" />
                  </div>
                )}
                <label className="flex items-center gap-2 mb-3">
                  <input type="checkbox" className="rounded border-gray-300" checked={form.kb_enabled} onChange={(e) => setForm({ ...form, kb_enabled: e.target.checked })} />
                  <span className="text-sm text-gray-700">Enable Knowledge Base search (Confluence)</span>
                </label>
                {form.kb_enabled && (
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Confluence Space Keys (comma-separated)</label>
                    <input className="input-field" value={form.kb_space_keys} onChange={(e) => setForm({ ...form, kb_space_keys: e.target.value })} placeholder="KB, OPS, RUNBOOK" />
                  </div>
                )}
              </div>

              <label className="flex items-center gap-2">
                <input type="checkbox" className="rounded border-gray-300" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
                <span className="text-sm text-gray-700">Active</span>
              </label>
            </div>
            <div className="flex justify-between items-center mt-6">
              <button onClick={handleTestConnection} disabled={testing} className="btn-accent flex items-center gap-1 text-sm disabled:opacity-50">
                <HeartPulse className={`h-4 w-4 ${testing ? 'animate-pulse' : ''}`} /> {testing ? 'Testing…' : 'Test Connection'}
              </button>
              <div className="flex gap-2">
                <button onClick={() => setShowModal(false)} className="btn-secondary">Cancel</button>
                <button onClick={handleSubmit} className="btn-primary flex items-center gap-1"><Check className="h-4 w-4" /> {editServer ? 'Save' : 'Create'}</button>
              </div>
            </div>
            {testResult && (
              <div className={`mt-3 p-3 rounded-lg text-sm ${testResult.status === 'healthy' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
                <strong>{testResult.status === 'healthy' ? '✓ Connection successful' : '✗ Connection failed'}</strong>
                {testResult.server_title && <span className="ml-2 text-xs">({testResult.server_title} v{testResult.version})</span>}
                {testResult.error && <p className="mt-1 text-xs">{testResult.error}</p>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
