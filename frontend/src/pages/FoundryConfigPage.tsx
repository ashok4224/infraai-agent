import { useState, useEffect, useCallback } from 'react';
import {
  Plus, Trash2, Save, TestTube, Loader2, CheckCircle, XCircle,
  RefreshCw, Settings, Mail, Search as SearchIcon,
} from 'lucide-react';
import api from '../api/client';

interface FoundryAgent {
  id: string;
  agent_name: string;
  foundry_agent_id: string;
  agent_line: string;
  role: string;
  system_type: string;
  trigger_labels: Record<string, string[]>;
  pipeline_order: number;
  is_optional: boolean;
  is_active: boolean;
  description: string | null;
  config_json: Record<string, unknown>;
}

const AGENT_LINES = ['workflow', 'technology'];
const ROLES = ['knowledge', 'triage_master', 'researcher', 'collector', 'solution', 'solver', 'validation', 'notifier', 'chat', 'specialist'];
const SYSTEM_TYPES = ['all', 'oracle', 'postgresql', 'mysql', 'sqlserver', 'mongodb', 'linux', 'cloud', 'kubernetes', 'infrastructure'];

export default function FoundryConfigPage() {
  const [agents, setAgents] = useState<FoundryAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<Partial<FoundryAgent>>({});
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [testing, setTesting] = useState<string | null>(null);

  const loadAgents = useCallback(async () => {
    try {
      const res = await api.get('/foundry/config');
      setAgents(res.data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAgents(); }, [loadAgents]);

  const startEdit = (agent?: FoundryAgent) => {
    if (agent) {
      setEditingId(agent.id);
      setForm({ ...agent });
    } else {
      setEditingId('new');
      setForm({
        agent_name: '', foundry_agent_id: '', agent_line: 'workflow', role: 'researcher',
        system_type: 'all', trigger_labels: {}, pipeline_order: 0,
        is_optional: false, is_active: true, description: '', config_json: {},
      });
    }
  };

  const saveAgent = async () => {
    setSaving(true);
    try {
      if (editingId === 'new') {
        await api.post('/foundry/config', form);
      } else {
        await api.put(`/foundry/config/${editingId}`, form);
      }
      setEditingId(null);
      setForm({});
      await loadAgents();
    } finally {
      setSaving(false);
    }
  };

  const deleteAgent = async (id: string) => {
    if (!confirm('Delete this agent config?')) return;
    await api.delete(`/foundry/config/${id}`);
    await loadAgents();
  };

  const testConnection = async () => {
    setTesting('connection');
    setTestResult(null);
    try {
      const res = await api.post('/foundry/test');
      setTestResult(res.data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Test failed';
      setTestResult({ success: false, message: msg });
    } finally {
      setTesting(null);
    }
  };

  const testAgent = async (id: string) => {
    setTesting(id);
    setTestResult(null);
    try {
      const res = await api.post(`/foundry/test-agent/${id}`);
      setTestResult(res.data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Agent test failed';
      setTestResult({ success: false, message: msg });
    } finally {
      setTesting(null);
    }
  };

  const testOutlook = async () => {
    setTesting('outlook');
    setTestResult(null);
    try {
      const res = await api.post('/foundry/test-outlook');
      setTestResult(res.data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Outlook test failed';
      setTestResult({ success: false, message: msg });
    } finally {
      setTesting(null);
    }
  };

  const testSharepoint = async () => {
    setTesting('sharepoint');
    setTestResult(null);
    try {
      const res = await api.post('/foundry/test-sharepoint');
      setTestResult(res.data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'SharePoint test failed';
      setTestResult({ success: false, message: msg });
    } finally {
      setTesting(null);
    }
  };

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Azure AI Foundry Configuration</h1>
          <p className="text-sm text-gray-500 mt-1">Manage Foundry agents, test integrations, and configure the analysis pipeline.</p>
        </div>
        <button onClick={() => startEdit()} className="btn btn-primary flex items-center gap-2">
          <Plus className="h-4 w-4" /> Add Agent
        </button>
      </div>

      {/* Test result banner */}
      {testResult && (
        <div className={`rounded-lg p-4 flex items-start gap-3 ${testResult.success ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
          {testResult.success ? <CheckCircle className="h-5 w-5 text-green-500 mt-0.5" /> : <XCircle className="h-5 w-5 text-red-500 mt-0.5" />}
          <div>
            <p className="font-medium">{testResult.success ? 'Success' : 'Failed'}</p>
            <p className="text-sm mt-1">{testResult.message}</p>
          </div>
          <button onClick={() => setTestResult(null)} className="ml-auto text-gray-400 hover:text-gray-600">
            <XCircle className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Integration tests */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Settings className="h-5 w-5" /> Integration Tests
        </h2>
        <div className="flex flex-wrap gap-3">
          <button onClick={testConnection} disabled={testing === 'connection'} className="btn btn-secondary flex items-center gap-2">
            {testing === 'connection' ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Test Foundry Connection
          </button>
          <button onClick={testOutlook} disabled={testing === 'outlook'} className="btn btn-secondary flex items-center gap-2">
            {testing === 'outlook' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
            Test Outlook
          </button>
          <button onClick={testSharepoint} disabled={testing === 'sharepoint'} className="btn btn-secondary flex items-center gap-2">
            {testing === 'sharepoint' ? <Loader2 className="h-4 w-4 animate-spin" /> : <SearchIcon className="h-4 w-4" />}
            Test SharePoint / AI Search
          </button>
        </div>
      </div>

      {/* Agent pipeline table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="p-6 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Agent Pipeline</h2>
          <p className="text-sm text-gray-500 mt-1">Use `workflow` agents for triage and orchestration, and `technology` agents for domain specialists like Linux, Cloud, Database, or Kubernetes.</p>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600">
            <tr>
              <th className="px-4 py-3 text-left font-medium">Order</th>
              <th className="px-4 py-3 text-left font-medium">Name</th>
              <th className="px-4 py-3 text-left font-medium">Line</th>
              <th className="px-4 py-3 text-left font-medium">Role</th>
              <th className="px-4 py-3 text-left font-medium">System Type</th>
              <th className="px-4 py-3 text-left font-medium">Agent ID</th>
              <th className="px-4 py-3 text-center font-medium">Active</th>
              <th className="px-4 py-3 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {agents.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">No agents configured. Click "Add Agent" to get started.</td></tr>
            ) : (
              agents.sort((a, b) => a.pipeline_order - b.pipeline_order).map(agent => (
                <tr key={agent.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono text-gray-500">{agent.pipeline_order}</td>
                  <td className="px-4 py-3 font-medium text-gray-900">{agent.agent_name}</td>
                  <td className="px-4 py-3 text-gray-600">{agent.agent_line}</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium bg-blue-50 text-blue-700">
                      {agent.role}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{agent.system_type}</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-500 truncate max-w-[200px]">{agent.foundry_agent_id}</td>
                  <td className="px-4 py-3 text-center">
                    {agent.is_active ? (
                      <CheckCircle className="h-4 w-4 text-green-500 inline" />
                    ) : (
                      <XCircle className="h-4 w-4 text-gray-300 inline" />
                    )}
                  </td>
                  <td className="px-4 py-3 text-right space-x-2">
                    <button
                      onClick={() => testAgent(agent.id)}
                      disabled={testing === agent.id}
                      className="text-gray-400 hover:text-blue-600 transition-colors"
                      title="Test agent"
                    >
                      {testing === agent.id ? <Loader2 className="h-4 w-4 inline animate-spin" /> : <TestTube className="h-4 w-4 inline" />}
                    </button>
                    <button onClick={() => startEdit(agent)} className="text-gray-400 hover:text-brand-600 transition-colors" title="Edit">
                      <Settings className="h-4 w-4 inline" />
                    </button>
                    <button onClick={() => deleteAgent(agent.id)} className="text-gray-400 hover:text-red-600 transition-colors" title="Delete">
                      <Trash2 className="h-4 w-4 inline" />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Edit modal */}
      {editingId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg p-6 space-y-4 max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-bold">{editingId === 'new' ? 'Add Agent' : 'Edit Agent'}</h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">Agent Name</label>
                <input
                  value={form.agent_name || ''}
                  onChange={e => setForm(f => ({ ...f, agent_name: e.target.value }))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">Foundry Agent ID</label>
                <input
                  value={form.foundry_agent_id || ''}
                  onChange={e => setForm(f => ({ ...f, foundry_agent_id: e.target.value }))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Agent Line</label>
                <select
                  value={form.agent_line || 'workflow'}
                  onChange={e => setForm(f => ({
                    ...f,
                    agent_line: e.target.value,
                    role: e.target.value === 'technology' ? 'specialist' : (f.role === 'specialist' ? 'researcher' : f.role),
                    system_type: e.target.value === 'technology' && (f.system_type || 'all') === 'all' ? 'linux' : f.system_type,
                  }))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                >
                  {AGENT_LINES.map(line => <option key={line} value={line}>{line}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
                <select
                  value={form.role || 'researcher'}
                  onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                >
                  {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">System Type</label>
                <select
                  value={form.system_type || 'all'}
                  onChange={e => setForm(f => ({ ...f, system_type: e.target.value }))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                >
                  {SYSTEM_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Pipeline Order</label>
                <input
                  type="number"
                  value={form.pipeline_order ?? 0}
                  onChange={e => setForm(f => ({ ...f, pipeline_order: parseInt(e.target.value) || 0 }))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div className="flex items-end gap-4">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.is_active ?? true}
                    onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))}
                  />
                  Active
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.is_optional ?? false}
                    onChange={e => setForm(f => ({ ...f, is_optional: e.target.checked }))}
                  />
                  Optional
                </label>
              </div>
              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <textarea
                  value={form.description || ''}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  rows={2}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <button onClick={() => { setEditingId(null); setForm({}); }} className="btn btn-secondary">Cancel</button>
              <button onClick={saveAgent} disabled={saving} className="btn btn-primary flex items-center gap-2">
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
