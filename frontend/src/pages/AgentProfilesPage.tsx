import { useEffect, useState } from 'react';
import api from '../api/client';
import { Plus, Pencil, Trash2, X, Check, Bot, Star, StarOff } from 'lucide-react';
import clsx from 'clsx';

interface AgentProfile {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  system_prompt: string;
  match_keywords: string[];
  match_labels: Record<string, string[]>;
  priority: number;
  agent_type: string;
  is_active: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

const emptyForm = {
  name: '',
  display_name: '',
  description: '',
  system_prompt: '',
  match_keywords: '',
  match_labels: '',
  priority: 0,
  agent_type: 'general',
  is_active: true,
  is_default: false,
};

export default function AgentProfilesPage() {
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editProfile, setEditProfile] = useState<AgentProfile | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchProfiles = () => {
    setLoading(true);
    api.get('/agent-profiles/').then((res) => setProfiles(res.data)).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(() => { fetchProfiles(); }, []);

  const openCreate = () => {
    setEditProfile(null);
    setForm(emptyForm);
    setShowModal(true);
    setError(null);
  };

  const openEdit = (profile: AgentProfile) => {
    setEditProfile(profile);
    setForm({
      name: profile.name,
      display_name: profile.display_name,
      description: profile.description || '',
      system_prompt: profile.system_prompt,
      match_keywords: profile.match_keywords.join(', '),
      match_labels: JSON.stringify(profile.match_labels, null, 2),
      priority: profile.priority,
      agent_type: profile.agent_type || 'general',
      is_active: profile.is_active,
      is_default: profile.is_default,
    });
    setShowModal(true);
    setError(null);
  };

  const handleSubmit = async () => {
    setError(null);
    let parsedLabels = {};
    try {
      if (form.match_labels.trim()) {
        parsedLabels = JSON.parse(form.match_labels);
      }
    } catch {
      setError('Match Labels must be valid JSON (e.g., {"job": ["oracle_exporter"]})');
      return;
    }

    const payload = {
      name: form.name,
      display_name: form.display_name,
      description: form.description || null,
      system_prompt: form.system_prompt,
      match_keywords: form.match_keywords.split(',').map((k: string) => k.trim()).filter(Boolean),
      match_labels: parsedLabels,
      priority: form.priority,
      agent_type: form.agent_type,
      is_active: form.is_active,
      is_default: form.is_default,
    };

    try {
      if (editProfile) {
        await api.patch(`/agent-profiles/${editProfile.id}`, payload);
      } else {
        await api.post('/agent-profiles/', payload);
      }
      setShowModal(false);
      fetchProfiles();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save agent profile');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this agent profile?')) return;
    await api.delete(`/agent-profiles/${id}`);
    fetchProfiles();
  };

  if (loading) {
    return <div className="flex justify-center py-20"><div className="animate-spin h-8 w-8 border-4 border-brand-500 border-t-transparent rounded-full" /></div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">Agent Profiles</h3>
          <p className="text-sm text-gray-500 mt-1">Define specialized AI agents with role-specific prompts. Alerts are auto-routed to the best-matching agent based on keywords and labels.</p>
        </div>
        <button onClick={openCreate} className="flex items-center gap-2 rounded-lg bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600">
          <Plus className="h-4 w-4" /> New Agent
        </button>
      </div>

      <div className="grid gap-4">
        {profiles.map((profile) => (
          <div key={profile.id} className={clsx('rounded-xl border bg-white shadow-sm', profile.is_default && 'border-brand-300 ring-1 ring-brand-100')}>
            <div className="flex items-center justify-between p-5">
              <div className="flex items-center gap-4">
                <div className={clsx('flex h-11 w-11 items-center justify-center rounded-lg', profile.is_active ? 'bg-brand-100 text-brand-600' : 'bg-gray-100 text-gray-400')}>
                  <Bot className="h-6 w-6" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-gray-900">{profile.display_name}</h3>
                    {profile.is_default && <span className="rounded-full bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-700">Default</span>}
                    {!profile.is_active && <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500">Inactive</span>}
                    <span className={clsx('rounded-full px-2 py-0.5 text-xs font-medium',
                      profile.agent_type === 'os' ? 'bg-green-100 text-green-700' :
                      profile.agent_type === 'database' ? 'bg-blue-100 text-blue-700' :
                      'bg-gray-100 text-gray-600'
                    )}>{profile.agent_type === 'os' ? 'OS Agent' : profile.agent_type === 'database' ? 'DB Agent' : 'General'}</span>
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">Priority: {profile.priority}</span>
                  </div>
                  <p className="text-sm text-gray-500 mt-0.5">{profile.description}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => setExpandedId(expandedId === profile.id ? null : profile.id)} className="rounded-lg border px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50">
                  {expandedId === profile.id ? 'Hide' : 'View'} Prompt
                </button>
                <button onClick={() => openEdit(profile)} className="rounded-lg border px-2 py-1.5 text-gray-400 hover:text-brand-600 hover:border-brand-300">
                  <Pencil className="h-4 w-4" />
                </button>
                <button onClick={() => handleDelete(profile.id)} className="rounded-lg border px-2 py-1.5 text-gray-400 hover:text-red-600 hover:border-red-300">
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* Keywords & Labels summary */}
            <div className="border-t px-5 py-3 flex flex-wrap gap-2">
              {profile.match_keywords.length > 0 && profile.match_keywords.map((kw) => (
                <span key={kw} className="rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">{kw}</span>
              ))}
              {Object.entries(profile.match_labels).map(([key, values]) => (
                <span key={key} className="rounded-md bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
                  {key}: {Array.isArray(values) ? values.join(', ') : String(values)}
                </span>
              ))}
              {profile.match_keywords.length === 0 && Object.keys(profile.match_labels).length === 0 && (
                <span className="text-xs text-gray-400 italic">No matching rules — acts as fallback</span>
              )}
            </div>

            {/* Expanded system prompt */}
            {expandedId === profile.id && (
              <div className="border-t bg-gray-50 p-5">
                <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">System Prompt</h4>
                <pre className="whitespace-pre-wrap text-sm text-gray-700 bg-white p-4 rounded-lg border max-h-80 overflow-y-auto">{profile.system_prompt}</pre>
              </div>
            )}
          </div>
        ))}

        {profiles.length === 0 && (
          <div className="text-center py-16 text-gray-400">
            <Bot className="h-12 w-12 mx-auto mb-3 opacity-40" />
            <p className="font-medium">No agent profiles defined</p>
            <p className="text-sm mt-1">Create your first agent to get started.</p>
          </div>
        )}
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold">{editProfile ? 'Edit' : 'New'} Agent Profile</h2>
              <button onClick={() => setShowModal(false)}><X className="h-5 w-5 text-gray-400" /></button>
            </div>
            {error && <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name (slug)</label>
                  <input className="w-full rounded-lg border px-3 py-2 text-sm" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="database_agent" disabled={!!editProfile} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
                  <input className="w-full rounded-lg border px-3 py-2 text-sm" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} placeholder="Database Agent" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <input className="w-full rounded-lg border px-3 py-2 text-sm" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Specializes in database alerts..." />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">System Prompt</label>
                <textarea className="w-full rounded-lg border px-3 py-2 text-sm font-mono" rows={10} value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} placeholder="You are an expert Database Reliability Engineer..." />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Match Keywords <span className="font-normal text-gray-400">(comma-separated)</span></label>
                <input className="w-full rounded-lg border px-3 py-2 text-sm" value={form.match_keywords} onChange={(e) => setForm({ ...form, match_keywords: e.target.value })} placeholder="oracle, database, tablespace, sql, session" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Match Labels <span className="font-normal text-gray-400">(JSON)</span></label>
                <textarea className="w-full rounded-lg border px-3 py-2 text-sm font-mono" rows={3} value={form.match_labels} onChange={(e) => setForm({ ...form, match_labels: e.target.value })} placeholder='{"job": ["oracle_exporter", "postgres_exporter"]}' />
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Agent Type</label>
                  <select className="w-full rounded-lg border px-3 py-2 text-sm bg-white" value={form.agent_type} onChange={(e) => setForm({ ...form, agent_type: e.target.value })}>
                    <option value="general">General (hybrid)</option>
                    <option value="os">OS (SSH commands only)</option>
                    <option value="database">Database (MCP/SQL only)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Priority</label>
                  <input type="number" className="w-full rounded-lg border px-3 py-2 text-sm" value={form.priority} onChange={(e) => setForm({ ...form, priority: parseInt(e.target.value) || 0 })} />
                </div>
                <div className="flex items-end gap-4">
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} className="rounded" /> Active
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.is_default} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} className="rounded" /> Default Fallback
                  </label>
                </div>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button onClick={() => setShowModal(false)} className="rounded-lg border px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
              <button onClick={handleSubmit} className="flex items-center gap-2 rounded-lg bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600">
                <Check className="h-4 w-4" /> {editProfile ? 'Update' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
