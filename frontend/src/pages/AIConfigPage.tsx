import { useEffect, useState } from 'react';
import api from '../api/client';
import { Plus, Pencil, Trash2, X, Check, Zap, Eye, EyeOff } from 'lucide-react';

interface AIProvider {
  id: string;
  provider: string;
  display_name: string;
  model_name: string;
  base_url: string | null;
  is_active: boolean;
  is_default: boolean;
  max_tokens: number;
  temperature: number;
  extra_params: Record<string, any>;
  has_api_key: boolean;
  created_at: string;
}

const PROVIDERS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic Claude' },
  { value: 'google', label: 'Google Gemini' },
  { value: 'custom', label: 'Custom Provider' },
];

export default function AIConfigPage() {
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editProvider, setEditProvider] = useState<AIProvider | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  const emptyForm = { provider: 'openai', display_name: '', api_key: '', model_name: '', base_url: '', is_active: false, is_default: false, max_tokens: 4096, temperature: 0.2 };
  const [form, setForm] = useState(emptyForm);
  const [showKey, setShowKey] = useState(false);

  const fetchProviders = () => {
    setLoading(true);
    api.get('/ai-config/').then((res) => setProviders(res.data)).finally(() => setLoading(false));
  };

  useEffect(() => { fetchProviders(); }, []);

  const openCreate = () => {
    setEditProvider(null);
    setForm(emptyForm);
    setShowModal(true);
    setShowKey(false);
  };

  const openEdit = (p: AIProvider) => {
    setEditProvider(p);
    setForm({
      provider: p.provider,
      display_name: p.display_name,
      api_key: '',
      model_name: p.model_name,
      base_url: p.base_url || '',
      is_active: p.is_active,
      is_default: p.is_default,
      max_tokens: p.max_tokens,
      temperature: p.temperature,
    });
    setShowModal(true);
    setShowKey(false);
  };

  const [submitError, setSubmitError] = useState('');

  const handleSubmit = async () => {
    setSubmitError('');
    try {
      if (editProvider) {
        const data: any = { ...form };
        if (!data.api_key) delete data.api_key; // don't overwrite if blank
        await api.patch(`/ai-config/${editProvider.id}`, data);
      } else {
        await api.post('/ai-config/', form);
      }
      setShowModal(false);
      fetchProviders();
    } catch (err: any) {
      setSubmitError(err.response?.data?.detail || 'Failed to save provider. Check if this provider already exists.');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this provider?')) return;
    await api.delete(`/ai-config/${id}`);
    fetchProviders();
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    setTestResult(null);
    try {
      const res = await api.post(`/ai-config/${id}/test`);
      setTestResult(res.data);
    } catch (err: any) {
      setTestResult({ success: false, message: err.response?.data?.detail || 'Test failed' });
    } finally {
      setTesting(null);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-lg font-semibold text-gray-800">AI Provider Configuration</h3>
          <p className="text-sm text-gray-500 mt-1">Configure OpenAI, Anthropic Claude, Google Gemini or custom AI providers</p>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus className="h-4 w-4" /> Add Provider
        </button>
      </div>

      {testResult && (
        <div className={`mb-4 rounded-lg px-4 py-3 text-sm ${testResult.success ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
          {testResult.message}
          <button onClick={() => setTestResult(null)} className="float-right"><X className="h-4 w-4" /></button>
        </div>
      )}

      <div className="grid gap-4">
        {loading ? (
          <div className="card flex justify-center py-12"><div className="animate-spin h-6 w-6 border-4 border-brand-500 border-t-transparent rounded-full" /></div>
        ) : providers.length === 0 ? (
          <div className="card text-center py-12 text-gray-400">No AI providers configured</div>
        ) : (
          providers.map((p) => (
            <div key={p.id} className={`card flex flex-col sm:flex-row items-start sm:items-center gap-4 ${p.is_default ? 'ring-2 ring-brand-500' : ''}`}>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold text-gray-800">{p.display_name}</h3>
                  {p.is_default && <span className="badge badge-info">Default</span>}
                  <span className={`badge ${p.is_active ? 'badge-success' : 'bg-gray-100 text-gray-500'}`}>{p.is_active ? 'Active' : 'Inactive'}</span>
                </div>
                <div className="mt-1 text-sm text-gray-500 flex flex-wrap gap-x-4 gap-y-1">
                  <span>Provider: <strong>{p.provider}</strong></span>
                  <span>Model: <strong>{p.model_name}</strong></span>
                  <span>Tokens: {p.max_tokens}</span>
                  <span>Temp: {p.temperature}</span>
                  <span>API Key: {p.has_api_key ? '✓ Set' : '✗ Not set'}</span>
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => handleTest(p.id)} disabled={testing === p.id} className="btn-accent text-sm py-1.5 px-3 flex items-center gap-1 disabled:opacity-50">
                  <Zap className={`h-3.5 w-3.5 ${testing === p.id ? 'animate-pulse' : ''}`} /> Test
                </button>
                <button onClick={() => openEdit(p)} className="btn-secondary text-sm py-1.5 px-3 flex items-center gap-1">
                  <Pencil className="h-3.5 w-3.5" /> Edit
                </button>
                <button onClick={() => handleDelete(p.id)} className="btn-danger text-sm py-1.5 px-3 flex items-center gap-1">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowModal(false)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">{editProvider ? 'Edit Provider' : 'Add AI Provider'}</h3>
              <button onClick={() => setShowModal(false)} className="p-1 rounded hover:bg-gray-100"><X className="h-5 w-5" /></button>
            </div>
            {submitError && (
              <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{submitError}</div>
            )}
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Provider</label>
                  <select className="input-field" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} disabled={!!editProvider}>
                    {PROVIDERS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
                  <input className="input-field" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">API Key {editProvider && '(leave blank to keep current)'}</label>
                <div className="relative">
                  <input className="input-field pr-10" type={showKey ? 'text' : 'password'} value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} placeholder="sk-..." />
                  <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2" onClick={() => setShowKey(!showKey)}>
                    {showKey ? <EyeOff className="h-4 w-4 text-gray-400" /> : <Eye className="h-4 w-4 text-gray-400" />}
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Model Name</label>
                  <input className="input-field" value={form.model_name} onChange={(e) => setForm({ ...form, model_name: e.target.value })} placeholder="e.g. gpt-4.1, claude-opus-4, gemini-2.5-flash" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Base URL (optional)</label>
                  <input className="input-field" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://api.openai.com/v1" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Max Tokens</label>
                  <input className="input-field" type="number" value={form.max_tokens} onChange={(e) => setForm({ ...form, max_tokens: Number(e.target.value) })} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Temperature</label>
                  <input className="input-field" type="number" step="0.1" min="0" max="2" value={form.temperature} onChange={(e) => setForm({ ...form, temperature: Number(e.target.value) })} />
                </div>
              </div>
              <div className="flex gap-6">
                <label className="flex items-center gap-2">
                  <input type="checkbox" className="rounded border-gray-300" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
                  <span className="text-sm text-gray-700">Active</span>
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" className="rounded border-gray-300" checked={form.is_default} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} />
                  <span className="text-sm text-gray-700">Default Provider</span>
                </label>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button onClick={() => setShowModal(false)} className="btn-secondary">Cancel</button>
              <button onClick={handleSubmit} className="btn-primary flex items-center gap-1"><Check className="h-4 w-4" /> {editProvider ? 'Save' : 'Create'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
