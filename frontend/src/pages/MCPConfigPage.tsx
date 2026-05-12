import { useEffect, useState } from 'react';
import api from '../api/client';
import { Plus, Pencil, Trash2, X, Check, HeartPulse, Eye, EyeOff, Database } from 'lucide-react';

interface MCPServer {
  id: string;
  name: string;
  description: string | null;
  server_type: string;
  command: string;
  args: string[];
  env_vars: Record<string, string>;
  connection_string: string | null;
  oracle_host: string | null;
  oracle_port: number | null;
  oracle_service: string | null;
  oracle_user: string | null;
  has_password: boolean;
  is_active: boolean;
  tools_available: string[];
  health_status: string;
  last_health_check: string | null;
  created_at: string;
}

export default function MCPConfigPage() {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editServer, setEditServer] = useState<MCPServer | null>(null);
  const [checking, setChecking] = useState<string | null>(null);
  const [showPwd, setShowPwd] = useState(false);
  const [testResult, setTestResult] = useState<{ status: string; error?: string } | null>(null);
  const [testing, setTesting] = useState(false);

  const emptyForm = {
    name: '', description: '', server_type: 'oracle', command: 'sql',
    args: '' as string, env_vars: '{}', connection_string: '',
    oracle_host: '', oracle_port: 1521, oracle_service: '', oracle_user: '', oracle_password: '',
    is_active: true,
  };
  const [form, setForm] = useState(emptyForm);

  const fetchServers = () => {
    setLoading(true);
    api.get('/mcp-config/').then((res) => setServers(res.data)).finally(() => setLoading(false));
  };

  useEffect(() => { fetchServers(); }, []);

  const openCreate = () => {
    setEditServer(null);
    setForm(emptyForm);
    setTestResult(null);
    setShowModal(true);
  };

  const openEdit = (s: MCPServer) => {
    setEditServer(s);
    setForm({
      name: s.name,
      description: s.description || '',
      server_type: s.server_type,
      command: s.command,
      args: s.args.join(' '),
      env_vars: JSON.stringify(s.env_vars, null, 2),
      connection_string: s.connection_string || '',
      oracle_host: s.oracle_host || '',
      oracle_port: s.oracle_port || 1521,
      oracle_service: s.oracle_service || '',
      oracle_user: s.oracle_user || '',
      oracle_password: '',
      is_active: s.is_active,
    });
    setTestResult(null);
    setShowModal(true);
  };

  const handleSubmit = async () => {
    let envVars = {};
    try { envVars = JSON.parse(form.env_vars); } catch {}

    const data: any = {
      ...form,
      args: form.args ? form.args.split(' ').filter(Boolean) : [],
      env_vars: envVars,
      oracle_port: Number(form.oracle_port),
    };

    if (editServer) {
      if (!data.oracle_password) delete data.oracle_password;
      await api.patch(`/mcp-config/${editServer.id}`, data);
      setShowModal(false);
      fetchServers();
    } else {
      const res = await api.post('/mcp-config/', data);
      setShowModal(false);
      fetchServers();
      // Show health result as a warning if not healthy
      if (res.data?.health && res.data.health.status !== 'healthy') {
        const h = res.data.health;
        const hint = h.dsn ? `\nDSN tried: ${h.dsn}` : '';
        alert(`⚠️ Config saved, but database connectivity check failed:\n${h.error || 'Unknown error'}${hint}\n\nYou can update the settings and re-run Test Connection.`);
      }
    }
  };


  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      let envVars = {};
      try { envVars = JSON.parse(form.env_vars); } catch {}
      const data: any = {
        ...form,
        args: form.args ? form.args.split(' ').filter(Boolean) : [],
        env_vars: envVars,
        oracle_port: Number(form.oracle_port),
      };
      const res = await api.post('/mcp-config/test-connection', data);
      setTestResult(res.data);
    } catch (err: any) {
      setTestResult({ status: 'unhealthy', error: err.response?.data?.detail || err.message });
    } finally {
      setTesting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this MCP server?')) return;
    await api.delete(`/mcp-config/${id}`);
    fetchServers();
  };

  const handleHealthCheck = async (id: string) => {
    setChecking(id);
    try {
      await api.post(`/mcp-config/${id}/health-check`);
      fetchServers();
    } finally {
      setChecking(null);
    }
  };

  const healthBadge = (status: string) => {
    const cls = { healthy: 'badge-success', unhealthy: 'badge-critical', unknown: 'badge-warning' }[status] || 'badge-warning';
    return <span className={`badge ${cls}`}>{status}</span>;
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-lg font-semibold text-gray-800">Database & Tools (MCP)</h3>
          <p className="text-sm text-gray-500 mt-1">Configure connections to databases via Model Context Protocol</p>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus className="h-4 w-4" /> Add Connection
        </button>
      </div>

      <div className="grid gap-4">
        {loading ? (
          <div className="card flex justify-center py-12"><div className="animate-spin h-6 w-6 border-4 border-brand-500 border-t-transparent rounded-full" /></div>
        ) : servers.length === 0 ? (
          <div className="card text-center py-12">
            <Database className="h-10 w-10 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-400">No MCP servers configured</p>
            <p className="text-xs text-gray-400 mt-1">Add an Oracle SQLcl MCP server to enable database queries</p>
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
                  </div>
                  {s.description && <p className="text-sm text-gray-500 mb-2">{s.description}</p>}
                  <div className="text-sm text-gray-500 flex flex-wrap gap-x-4 gap-y-1">
                    <span>Type: <strong>{s.server_type}</strong></span>
                    <span>Command: <code className="bg-gray-100 px-1 rounded text-xs">{s.command} {s.args.join(' ')}</code></span>
                    {s.oracle_host && <span>Host: <strong>{s.oracle_host}:{s.oracle_port}</strong></span>}
                    {s.oracle_service && <span>Service: <strong>{s.oracle_service}</strong></span>}
                    {s.oracle_user && <span>User: <strong>{s.oracle_user}</strong></span>}
                  </div>
                  {s.tools_available.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {s.tools_available.map((t) => (
                        <span key={t} className="inline-block bg-brand-50 text-brand-600 text-xs px-2 py-0.5 rounded">{t}</span>
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
              <h3 className="text-lg font-semibold">{editServer ? 'Edit MCP Server' : 'Add MCP Server'}</h3>
              <button onClick={() => setShowModal(false)} className="p-1 rounded hover:bg-gray-100"><X className="h-5 w-5" /></button>
            </div>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                  <input className="input-field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="db-prod-01" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Database Platform</label>
                  <select
                    className="input-field"
                    value={form.server_type}
                    onChange={(e) => {
                      const type = e.target.value;
                      let port = form.oracle_port;
                      let cmd = form.command;
                      let args = form.args;
                      if (type === 'oracle') { port = 1521; cmd = 'sql'; args = '-mcp'; }
                      else if (type === 'postgresql') { port = 5432; cmd = 'npx'; args = '-y @modelcontextprotocol/server-postgres postgresql://USER:PASS@HOST/DBNAME'; }
                      else if (type === 'mysql') { port = 3306; cmd = 'npx'; args = ''; }
                      else if (type === 'sqlserver') { port = 1433; cmd = 'npx'; args = ''; }

                      setForm({ ...form, server_type: type, oracle_port: port, command: cmd, args: args });
                    }}
                  >
                    <option value="oracle">Oracle</option>
                    <option value="postgresql">PostgreSQL</option>
                    <option value="mysql">MySQL</option>
                    <option value="sqlserver">SQL Server</option>
                    <option value="custom">Custom (Generic MCP)</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <input className="input-field" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Production Oracle database" />
              </div>

              <div className="border-t pt-3 mt-2">
                <p className="text-sm font-medium text-gray-700 mb-2">MCP Server Command</p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Command</label>
                    <input className="input-field" value={form.command} onChange={(e) => setForm({ ...form, command: e.target.value })} placeholder="sql" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Args (space-separated)</label>
                    <input className="input-field" value={form.args} onChange={(e) => setForm({ ...form, args: e.target.value })} placeholder="-mcp" />
                  </div>
                </div>
              </div>

              <div className="border-t pt-3 mt-2">
                <p className="text-sm font-medium text-gray-700 mb-2">Database Connection</p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Host</label>
                    <input className="input-field" value={form.oracle_host} onChange={(e) => setForm({ ...form, oracle_host: e.target.value })} placeholder="db-server-01" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Port</label>
                    <input className="input-field" type="number" value={form.oracle_port} onChange={(e) => setForm({ ...form, oracle_port: Number(e.target.value) })} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3 mt-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">
                      {form.server_type === 'oracle' ? 'Service Name' : 'Database Name'}
                    </label>
                    <input className="input-field" value={form.oracle_service} onChange={(e) => setForm({ ...form, oracle_service: e.target.value })} placeholder={form.server_type === 'oracle' ? 'ORCL' : 'public'} />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Username</label>
                    <input className="input-field" value={form.oracle_user} onChange={(e) => setForm({ ...form, oracle_user: e.target.value })} placeholder={form.server_type === 'oracle' ? 'system' : 'root'} />
                  </div>
                </div>
                <div className="mt-3">
                  <label className="block text-xs text-gray-500 mb-1">Password {editServer && '(leave blank to keep current)'}</label>
                  <div className="relative">
                    <input className="input-field pr-10" type={showPwd ? 'text' : 'password'} value={form.oracle_password} onChange={(e) => setForm({ ...form, oracle_password: e.target.value })} />
                    <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2" onClick={() => setShowPwd(!showPwd)}>
                      {showPwd ? <EyeOff className="h-4 w-4 text-gray-400" /> : <Eye className="h-4 w-4 text-gray-400" />}
                    </button>
                  </div>
                </div>
                <div className="mt-3">
                  <label className="block text-xs text-gray-500 mb-1">Or Full Connection String</label>
                  <input className="input-field" value={form.connection_string} onChange={(e) => setForm({ ...form, connection_string: e.target.value })} placeholder="user/pass@host:1521/service" />
                </div>
              </div>

              <div className="border-t pt-3">
                <label className="block text-sm font-medium text-gray-700 mb-1">Environment Variables (JSON)</label>
                <textarea className="input-field font-mono text-xs" rows={3} value={form.env_vars} onChange={(e) => setForm({ ...form, env_vars: e.target.value })} />
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
                {testResult.error && <p className="mt-1 text-xs">{testResult.error}</p>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
