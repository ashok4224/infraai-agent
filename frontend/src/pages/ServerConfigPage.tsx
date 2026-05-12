import { useState, useEffect, useRef } from 'react';
import { Server, Plus, Pencil, Trash2, RefreshCw, Terminal, Upload, Eye, EyeOff, Play, Shield } from 'lucide-react';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';

interface ServerConfig {
  id: string;
  name: string;
  description: string | null;
  host: string;
  port: number;
  username: string;
  auth_type: 'password' | 'key';
  has_password: boolean;
  has_private_key: boolean;
  sudo_enabled: boolean;
  has_sudo_password: boolean;
  os_type: string;
  tags: string | null;
  is_active: boolean;
  health_status: string;
  last_health_check: string | null;
}

const EMPTY_FORM = {
  name: '',
  description: '',
  host: '',
  port: 22,
  username: '',
  auth_type: 'password' as 'password' | 'key',
  ssh_password: '',
  ssh_private_key: '',
  sudo_enabled: true,
  sudo_password: '',
  os_type: 'linux',
  tags: '',
  is_active: true,
};

export default function ServerConfigPage() {
  const [servers, setServers] = useState<ServerConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editServer, setEditServer] = useState<ServerConfig | null>(null);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);
  const [checking, setChecking] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [showSudoPassword, setShowSudoPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Command runner state
  const [activeRunner, setActiveRunner] = useState<string | null>(null);
  const [command, setCommand] = useState('');
  const [useSudo, setUseSudo] = useState(false);
  const [cmdTimeout, setCmdTimeout] = useState(60);
  const [running, setRunning] = useState(false);
  const [cmdOutput, setCmdOutput] = useState<any>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const fetchServers = () => {
    setLoading(true);
    setPageError(null);
    api.get('/server-config/')
      .then(r => setServers(r.data))
      .catch(e => setPageError(e.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  };
  useEffect(() => { fetchServers(); }, []);

  const openCreate = () => {
    setEditServer(null);
    setForm({ ...EMPTY_FORM });
    setTestResult(null);
    setSaveError(null);
    setShowModal(true);
  };

  const openEdit = (s: ServerConfig) => {
    setEditServer(s);
    setForm({
      name: s.name, description: s.description || '', host: s.host, port: s.port,
      username: s.username, auth_type: s.auth_type,
      ssh_password: '', ssh_private_key: '', sudo_enabled: s.sudo_enabled,
      sudo_password: '', os_type: s.os_type, tags: s.tags || '', is_active: s.is_active,
    });
    setTestResult(null);
    setSaveError(null);
    setShowModal(true);
  };

  const handlePEMUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setForm(f => ({ ...f, ssh_private_key: ev.target?.result as string }));
      if (fileInputRef.current) fileInputRef.current.value = '';
    };
    reader.readAsText(file);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const data: any = { ...form };
      if (editServer) {
        // Don't overwrite credentials with empty strings on update
        if (!data.ssh_password) delete data.ssh_password;
        if (!data.ssh_private_key) delete data.ssh_private_key;
        if (!data.sudo_password) delete data.sudo_password;
        await api.patch(`/server-config/${editServer.id}`, data);
        setShowModal(false);
        fetchServers();
      } else {
        const res = await api.post('/server-config/', data);
        setShowModal(false);
        fetchServers();
        if (res.data?.health && res.data.health.status !== 'healthy') {
          const h = res.data.health;
          setPageError(`Server saved, but SSH check failed: ${h.error || 'Unknown error'}. Update settings and re-run Test Connection.`);
        }
      }
    } catch (err: any) {
      setSaveError(err.response?.data?.detail || err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.post('/server-config/test-connection', form);
      setTestResult(res.data);
    } catch (err: any) {
      setTestResult({ status: 'unhealthy', error: err.response?.data?.detail || err.message });
    } finally {
      setTesting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this server config?')) return;
    try {
      await api.delete(`/server-config/${id}`);
      fetchServers();
    } catch (err: any) {
      setPageError(err.response?.data?.detail || err.message);
    }
  };

  const handleHealthCheck = async (id: string) => {
    setChecking(id);
    try {
      await api.post(`/server-config/${id}/health-check`);
      fetchServers();
    } catch (err: any) {
      setPageError(err.response?.data?.detail || err.message);
    } finally {
      setChecking(null);
    }
  };

  // Reset command runner when switching to a different server
  const openRunner = (id: string) => {
    if (activeRunner !== id) {
      setCommand('');
      setUseSudo(false);
      setCmdOutput(null);
    }
    setActiveRunner(activeRunner === id ? null : id);
  };

  const handleRunCommand = async (id: string) => {
    if (!command.trim()) return;
    setRunning(true);
    setCmdOutput(null);
    try {
      const res = await api.post(`/server-config/${id}/run-command`, {
        command, use_sudo: useSudo, timeout: cmdTimeout,
      });
      setCmdOutput(res.data);
    } catch (err: any) {
      setCmdOutput({ success: false, error: err.response?.data?.detail || err.message });
    } finally {
      setRunning(false);
    }
  };

  const healthBadge = (status: string) => {
    const cls = { healthy: 'badge-success', unhealthy: 'badge-critical', unknown: 'badge-warning' }[status] || 'badge-warning';
    return <span className={`badge ${cls}`}>{status}</span>;
  };

  const f = (k: keyof typeof EMPTY_FORM, v: any) => setForm(prev => ({ ...prev, [k]: v }));

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">Server / SSH Connections</h3>
          <p className="text-sm text-gray-500 mt-1">Configure Linux/Windows servers for OS-level diagnostics and command execution.</p>
        </div>
        {isAdmin && (
          <button onClick={openCreate} className="btn-primary flex items-center gap-2">
            <Plus className="h-4 w-4" /> Add Server
          </button>
        )}
      </div>

      {pageError && (
        <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700 flex justify-between items-start">
          <span>{pageError}</span>
          <button onClick={() => setPageError(null)} className="ml-3 text-red-400 hover:text-red-600">×</button>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-12"><div className="animate-spin h-8 w-8 border-4 border-brand-500 border-t-transparent rounded-full" /></div>
      ) : servers.length === 0 ? (
        <div className="card text-center py-16">
          <Server className="h-12 w-12 text-gray-300 mx-auto mb-4" />
          <p className="text-gray-500">No servers configured yet.</p>
          {isAdmin && (
            <button onClick={openCreate} className="btn-primary mt-4">Add Your First Server</button>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {servers.map(s => (
            <div key={s.id} className="card">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="flex-shrink-0 p-2 rounded-lg bg-gray-100">
                    <Server className="h-5 w-5 text-gray-600" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-gray-800">{s.name}</span>
                      {healthBadge(s.health_status)}
                      <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">{s.os_type}</span>
                      <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded">{s.auth_type === 'key' ? '🔑 Key Auth' : '🔒 Password'}</span>
                      {s.sudo_enabled && <span className="text-xs bg-orange-50 text-orange-700 px-2 py-0.5 rounded flex items-center gap-1"><Shield className="h-3 w-3" />sudo</span>}
                    </div>
                    <p className="text-sm text-gray-500">{s.username}@{s.host}:{s.port}</p>
                    {s.description && <p className="text-xs text-gray-400 mt-0.5">{s.description}</p>}
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button onClick={() => openRunner(s.id)}
                    className="btn-secondary text-sm flex items-center gap-1.5">
                    <Terminal className="h-3.5 w-3.5" />Run
                  </button>
                  <button onClick={() => handleHealthCheck(s.id)} disabled={checking === s.id}
                    className="btn-secondary text-sm flex items-center gap-1.5">
                    <RefreshCw className={`h-3.5 w-3.5 ${checking === s.id ? 'animate-spin' : ''}`} />Test
                  </button>
                  {isAdmin && (
                    <>
                      <button onClick={() => openEdit(s)} className="btn-secondary text-sm flex items-center gap-1.5">
                        <Pencil className="h-3.5 w-3.5" />Edit
                      </button>
                      <button onClick={() => handleDelete(s.id)} className="text-red-500 hover:text-red-700 p-1.5 rounded-lg hover:bg-red-50">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </>
                  )}
                </div>
              </div>

              {/* Inline Command Runner */}
              {activeRunner === s.id && (
                <div className="mt-4 pt-4 border-t border-gray-100">
                  <h4 className="text-sm font-medium text-gray-700 mb-3 flex items-center gap-2">
                    <Terminal className="h-4 w-4 text-brand-500" />Command Runner
                  </h4>
                  <div className="flex gap-2 items-end">
                    <div className="flex-1">
                      <input type="text" value={command} onChange={e => setCommand(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleRunCommand(s.id)}
                        placeholder="e.g. df -h or systemctl status oracle"
                        className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 font-mono text-sm" />
                    </div>
                    <div className="flex items-center gap-3 pb-1">
                      {s.sudo_enabled && (
                        <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer">
                          <input type="checkbox" checked={useSudo} onChange={e => setUseSudo(e.target.checked)} className="rounded" />
                          sudo
                        </label>
                      )}
                      <select value={cmdTimeout} onChange={e => setCmdTimeout(Number(e.target.value))}
                        className="text-xs rounded-md border-gray-300">
                        <option value={30}>30s</option>
                        <option value={60}>60s</option>
                        <option value={120}>120s</option>
                        <option value={300}>5m</option>
                      </select>
                      <button onClick={() => handleRunCommand(s.id)} disabled={running || !command.trim()}
                        className="btn-primary text-sm flex items-center gap-1.5 py-2 disabled:opacity-50">
                        {running ? <div className="animate-spin h-3.5 w-3.5 border-2 border-white border-t-transparent rounded-full" /> : <Play className="h-3.5 w-3.5" />}
                        Run
                      </button>
                    </div>
                  </div>
                  {cmdOutput && (
                    <div className="mt-3">
                      <div className={`text-xs px-3 py-1.5 rounded-t-md flex justify-between ${cmdOutput.success ? 'bg-green-800 text-green-100' : 'bg-red-800 text-red-100'}`}>
                        <span>{cmdOutput.success ? '✓ Exit 0' : `✗ Exit ${cmdOutput.exit_code ?? 'error'}`}</span>
                        <span>{cmdOutput.host}</span>
                      </div>
                      <pre className="bg-gray-900 text-green-400 text-xs p-4 rounded-b-md overflow-x-auto max-h-64 whitespace-pre-wrap">
                        {cmdOutput.stdout || cmdOutput.error || '(no output)'}
                        {cmdOutput.stderr ? `\n--- stderr ---\n${cmdOutput.stderr}` : ''}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-black/40 flex items-start justify-center pt-8 pb-8">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl mx-4">
            <div className="flex justify-between items-center px-6 py-4 border-b">
              <h2 className="text-lg font-semibold text-gray-800">{editServer ? 'Edit Server' : 'Add Server'}</h2>
              <button onClick={() => setShowModal(false)} className="text-gray-400 hover:text-gray-600 text-2xl">×</button>
            </div>
            <div className="p-6 space-y-5 max-h-[75vh] overflow-y-auto">

              {/* Basic Info */}
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
                  <input className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm"
                    value={form.name} onChange={e => f('name', e.target.value)} placeholder="prod-ebs-app01" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Host / IP *</label>
                  <input className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm"
                    value={form.host} onChange={e => f('host', e.target.value)} placeholder="10.0.1.100 or ebs-app.corp.internal" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">SSH Port</label>
                  <input type="number" className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm"
                    value={form.port} onChange={e => f('port', Number(e.target.value))} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Username *</label>
                  <input className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm"
                    value={form.username} onChange={e => f('username', e.target.value)} placeholder="oracle / ec2-user / azureuser" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">OS Type</label>
                  <select className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm"
                    value={form.os_type} onChange={e => f('os_type', e.target.value)}>
                    <option value="linux">Linux</option>
                    <option value="windows">Windows</option>
                  </select>
                </div>
              </div>

              {/* Authentication */}
              <div className="border border-gray-200 rounded-lg p-4 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Authentication Type</label>
                  <div className="flex gap-4">
                    {(['password', 'key'] as const).map(t => (
                      <label key={t} className="flex items-center gap-2 cursor-pointer">
                        <input type="radio" name="auth_type" value={t} checked={form.auth_type === t}
                          onChange={() => f('auth_type', t)} />
                        <span className="text-sm">{t === 'password' ? '🔒 Password' : '🔑 SSH Private Key (PEM)'}</span>
                      </label>
                    ))}
                  </div>
                </div>

                {form.auth_type === 'password' ? (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      SSH Password {editServer && '(leave blank to keep existing)'}
                    </label>
                    <div className="relative">
                      <input type={showPassword ? 'text' : 'password'}
                        className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm pr-10"
                        value={form.ssh_password} onChange={e => f('ssh_password', e.target.value)} />
                      <button type="button" onClick={() => setShowPassword(p => !p)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400">
                        {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Private Key (PEM) {editServer && '(leave blank to keep existing)'}
                    </label>
                    <div className="flex gap-2 mb-2">
                      <button type="button" onClick={() => fileInputRef.current?.click()}
                        className="btn-secondary text-sm flex items-center gap-1.5">
                        <Upload className="h-3.5 w-3.5" />Upload .pem file
                      </button>
                      <input ref={fileInputRef} type="file" accept=".pem,.key" className="hidden" onChange={handlePEMUpload} />
                      <span className="text-xs text-gray-400 self-center">or paste below</span>
                    </div>
                    <textarea rows={6}
                      className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 font-mono text-xs resize-none"
                      placeholder="-----BEGIN RSA PRIVATE KEY-----&#10;...&#10;-----END RSA PRIVATE KEY-----"
                      value={form.ssh_private_key} onChange={e => f('ssh_private_key', e.target.value)} />
                  </div>
                )}
              </div>

              {/* Sudo */}
              <div className="border border-gray-200 rounded-lg p-4 space-y-3">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={form.sudo_enabled} onChange={e => f('sudo_enabled', e.target.checked)} className="rounded" />
                  <span className="text-sm font-medium text-gray-700"><Shield className="inline h-4 w-4 mr-1 text-orange-500" />Enable sudo execution</span>
                </label>
                {form.sudo_enabled && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Sudo Password <span className="text-gray-400 font-normal">(leave blank if passwordless sudo)</span>
                    </label>
                    <div className="relative">
                      <input type={showSudoPassword ? 'text' : 'password'}
                        className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm pr-10"
                        value={form.sudo_password} onChange={e => f('sudo_password', e.target.value)} />
                      <button type="button" onClick={() => setShowSudoPassword(p => !p)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400">
                        {showSudoPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* Optional fields */}
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                  <input className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm"
                    value={form.description} onChange={e => f('description', e.target.value)} placeholder="EBS App Tier — Production" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Tags (comma-separated)</label>
                  <input className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm"
                    value={form.tags} onChange={e => f('tags', e.target.value)} placeholder="prod,ebs,oracle" />
                </div>
                <div className="flex items-center pt-6">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked={form.is_active} onChange={e => f('is_active', e.target.checked)} className="rounded" />
                    <span className="text-sm text-gray-700">Active</span>
                  </label>
                </div>
              </div>

              {/* Test Connection */}
              <div>
                <button onClick={handleTestConnection} disabled={testing || !form.host || !form.username}
                  className="btn-secondary flex items-center gap-2 disabled:opacity-50">
                  {testing ? <div className="animate-spin h-4 w-4 border-2 border-brand-500 border-t-transparent rounded-full" /> : <RefreshCw className="h-4 w-4" />}
                  Test SSH Connection
                </button>
                {testResult && (
                  <div className={`mt-3 p-3 rounded-lg text-sm ${testResult.status === 'healthy' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
                    {testResult.status === 'healthy' ? (
                      <><strong>✓ Connected!</strong><br /><span className="font-mono text-xs">{testResult.sysinfo}</span></>
                    ) : (
                      <><strong>✗ Failed:</strong> {testResult.error}</>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className="flex justify-end gap-3 px-6 py-4 border-t bg-gray-50 rounded-b-xl">
              <button onClick={() => setShowModal(false)} className="btn-secondary">Cancel</button>
              {saveError && (
                <p className="flex-1 text-sm text-red-600 self-center">{saveError}</p>
              )}
              <button onClick={handleSave} disabled={saving || !form.name || !form.host || !form.username}
                className="btn-primary disabled:opacity-50">
                {saving ? 'Saving…' : editServer ? 'Update Server' : 'Save Server'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
