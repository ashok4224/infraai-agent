import { useState, useEffect, useCallback } from 'react';
import {
  knowledgeApi,
  KnowledgeSource,
  RAGSettings,
  KnowledgeSearchResult,
} from '../api/knowledge';
import {
  BookOpen, Plus, RefreshCw, Trash2, Search, Upload, TestTube,
  CheckCircle, XCircle, Clock, Loader2, Eye,
} from 'lucide-react';

const SOURCE_TYPES = [
  { value: 'github', label: 'GitHub', color: 'bg-gray-800 text-white' },
  { value: 'sharepoint', label: 'SharePoint', color: 'bg-blue-600 text-white' },
  { value: 'jira', label: 'Jira', color: 'bg-blue-500 text-white' },
  { value: 'servicenow', label: 'ServiceNow', color: 'bg-green-600 text-white' },
  { value: 'upload', label: 'File Upload', color: 'bg-purple-600 text-white' },
];

function Badge({ type }: { type: string }) {
  const st = SOURCE_TYPES.find((s) => s.value === type);
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${st?.color || 'bg-gray-200 text-gray-700'}`}>
      {st?.label || type}
    </span>
  );
}

function SyncStatusBadge({ status }: { status: string }) {
  if (status === 'completed') return <span className="flex items-center gap-1 text-green-600 text-xs"><CheckCircle className="h-3 w-3" /> Synced</span>;
  if (status === 'running') return <span className="flex items-center gap-1 text-blue-600 text-xs"><Loader2 className="h-3 w-3 animate-spin" /> Syncing…</span>;
  if (status === 'failed') return <span className="flex items-center gap-1 text-red-600 text-xs"><XCircle className="h-3 w-3" /> Failed</span>;
  return <span className="flex items-center gap-1 text-gray-500 text-xs"><Clock className="h-3 w-3" /> Idle</span>;
}

export default function KnowledgeBasePage() {
  const [settings, setSettings] = useState<RAGSettings | null>(null);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [showSearch, setShowSearch] = useState(false);

  const load = useCallback(async () => {
    try {
      const [settingsRes, sourcesRes] = await Promise.all([
        knowledgeApi.getSettings(),
        knowledgeApi.listSources(),
      ]);
      setSettings(settingsRes.data);
      setSources(sourcesRes.data);
      setError('');
    } catch (e: any) {
      if (e.response?.status === 403) {
        setError('RAG Knowledge Base feature is not enabled. Enable it in Settings → rag_enabled.');
      } else {
        setError(e.message || 'Failed to load knowledge base');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSync = async (id: string) => {
    try {
      await knowledgeApi.triggerSync(id);
      setSources((prev) => prev.map((s) => s.id === id ? { ...s, sync_status: 'running' } : s));
      // Poll status
      const poll = setInterval(async () => {
        try {
          const res = await knowledgeApi.getSyncStatus(id);
          const status = res.data;
          if (status.sync_status !== 'running') {
            clearInterval(poll);
            load();
          }
        } catch { clearInterval(poll); }
      }, 3000);
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Sync failed');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this knowledge source and all its indexed documents?')) return;
    try {
      await knowledgeApi.deleteSource(id);
      setSources((prev) => prev.filter((s) => s.id !== id));
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Delete failed');
    }
  };

  const handleTest = async (id: string) => {
    try {
      const res = await knowledgeApi.testConnection(id);
      alert(`Connection test: ${JSON.stringify(res.data, null, 2)}`);
    } catch (e: any) {
      alert(`Connection test failed: ${e.response?.data?.detail || e.message}`);
    }
  };

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>;

  if (error) {
    return (
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6 text-center">
        <BookOpen className="h-10 w-10 text-yellow-500 mx-auto mb-3" />
        <p className="text-yellow-800 font-medium">{error}</p>
        <p className="text-yellow-600 text-sm mt-2">
          Go to System Configuration → Settings and set <code className="bg-yellow-100 px-1 rounded">rag_enabled</code> to <code className="bg-yellow-100 px-1 rounded">true</code>.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-gray-800 flex items-center gap-2">
            <BookOpen className="h-5 w-5" /> Knowledge Base
          </h3>
          <p className="text-sm text-gray-500 mt-1">
            {settings?.rag_embedding_model} · chunk size {settings?.rag_chunk_size} · top-k {settings?.rag_top_k}
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowSearch(!showSearch)} className="btn-secondary flex items-center gap-1 px-3 py-2 text-sm border rounded-lg hover:bg-gray-50">
            <Search className="h-4 w-4" /> Search
          </button>
          <button onClick={() => setShowCreate(!showCreate)} className="flex items-center gap-1 px-3 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700">
            <Plus className="h-4 w-4" /> Add Source
          </button>
        </div>
      </div>

      {/* Search panel */}
      {showSearch && <SearchPanel />}

      {/* Create form */}
      {showCreate && <CreateSourceForm onCreated={() => { setShowCreate(false); load(); }} />}

      {/* Sources list */}
      {sources.length === 0 ? (
        <div className="bg-white rounded-lg border p-8 text-center text-gray-500">
          <BookOpen className="h-12 w-12 mx-auto mb-3 text-gray-300" />
          <p>No knowledge sources configured yet.</p>
          <p className="text-sm">Add a GitHub repo, SharePoint site, Jira project, ServiceNow instance, or upload files.</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {sources.map((source) => (
            <div key={source.id} className="bg-white rounded-lg border p-4 hover:shadow-sm transition-shadow">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <Badge type={source.source_type} />
                    <h4 className="font-medium text-gray-800">{source.name}</h4>
                    {!source.is_active && <span className="text-xs text-gray-400">(disabled)</span>}
                  </div>
                  {source.description && <p className="text-sm text-gray-500">{source.description}</p>}
                  <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                    <span>{source.doc_count} docs</span>
                    <span>{source.chunk_count} chunks</span>
                    <span>Sync every {source.sync_interval_hours}h</span>
                    <SyncStatusBadge status={source.sync_status} />
                    {source.last_synced_at && (
                      <span>Last: {new Date(source.last_synced_at).toLocaleString()}</span>
                    )}
                  </div>
                  {source.sync_error && <p className="text-xs text-red-500 mt-1">{source.sync_error}</p>}
                </div>
                <div className="flex gap-1">
                  <button onClick={() => handleTest(source.id)} title="Test connection" className="p-1.5 rounded hover:bg-gray-100">
                    <TestTube className="h-4 w-4 text-gray-500" />
                  </button>
                  <button onClick={() => handleSync(source.id)} title="Sync now" disabled={source.sync_status === 'running'} className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-40">
                    <RefreshCw className={`h-4 w-4 text-blue-500 ${source.sync_status === 'running' ? 'animate-spin' : ''}`} />
                  </button>
                  <button onClick={() => handleDelete(source.id)} title="Delete" className="p-1.5 rounded hover:bg-red-50">
                    <Trash2 className="h-4 w-4 text-red-500" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


// ── Create Source Form ──────────────────────────────────────────────────

function CreateSourceForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [sourceType, setSourceType] = useState('github');
  const [syncInterval, setSyncInterval] = useState(24);
  const [connectionConfig, setConnectionConfig] = useState('{}');
  const [filterConfig, setFilterConfig] = useState('{}');
  const [fileToUpload, setFileToUpload] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Set default filter config when source type changes
  useEffect(() => {
    const defaults: Record<string, object> = {
      github: { repos: [], branch: 'main', file_extensions: ['.md', '.txt', '.yaml', '.yml', '.json', '.tf'] },
      sharepoint: { site_ids: [], file_types: ['.md', '.txt', '.docx'] },
      jira: { project_keys: [], issue_types: ['Incident', 'Problem', 'Bug'], statuses: ['Done', 'Resolved', 'Closed'] },
      servicenow: { tables: ['incident', 'problem', 'kb_knowledge'], state_filter: ['Resolved', 'Closed'] },
      upload: { allowed_extensions: ['.md', '.txt', '.yaml', '.json'] },
    };
    setFilterConfig(JSON.stringify(defaults[sourceType] || {}, null, 2));
  }, [sourceType]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSaving(true);
    try {
      let conn = {}, filt = {};
      try { conn = JSON.parse(connectionConfig); } catch { throw new Error('Invalid connection config JSON'); }
      try { filt = JSON.parse(filterConfig); } catch { throw new Error('Invalid filter config JSON'); }
      const res = await knowledgeApi.createSource({ name, description: description || undefined, source_type: sourceType, connection_config: conn, filter_config: filt, sync_interval_hours: syncInterval, is_active: true });
      // If this is an upload source and a file was selected, upload it to the knowledge store
      if (sourceType === 'upload' && fileToUpload) {
        try {
          await knowledgeApi.uploadFile(fileToUpload);
        } catch (uploadErr: any) {
          // don't block creation, but surface error
          console.error('File upload failed', uploadErr);
          setError((uploadErr?.response?.data?.detail) || uploadErr?.message || 'File upload failed');
        }
      }
      onCreated();
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Failed to create');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-lg border p-5 space-y-4">
      <h4 className="font-medium text-gray-800">Add Knowledge Source</h4>
      {error && <p className="text-red-600 text-sm">{error}</p>}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} required className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="e.g. Infra Runbooks" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Source Type</label>
          <select value={sourceType} onChange={(e) => setSourceType(e.target.value)} className="w-full border rounded-lg px-3 py-2 text-sm">
            {SOURCE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
        <input value={description} onChange={(e) => setDescription(e.target.value)} className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="Optional description" />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Sync Interval (hours)</label>
        <input type="number" value={syncInterval} onChange={(e) => setSyncInterval(parseInt(e.target.value) || 24)} min={1} className="w-32 border rounded-lg px-3 py-2 text-sm" />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Connection Config (JSON)</label>
        {/* Hide connection config for simple uploads by leaving it editable but optional */}
        {sourceType !== 'upload' ? (
          <textarea value={connectionConfig} onChange={(e) => setConnectionConfig(e.target.value)} rows={3} className="w-full border rounded-lg px-3 py-2 text-sm font-mono" placeholder='{"token": "ghp_..."}' />
        ) : (
          <textarea value={connectionConfig} onChange={(e) => setConnectionConfig(e.target.value)} rows={2} className="w-full border rounded-lg px-3 py-2 text-sm font-mono" placeholder='{} (not required for local file upload)' />
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Filter Config (JSON)</label>
        <textarea value={filterConfig} onChange={(e) => setFilterConfig(e.target.value)} rows={5} className="w-full border rounded-lg px-3 py-2 text-sm font-mono" />
      </div>

      {sourceType === 'upload' && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Select File to Upload</label>
          <input type="file" onChange={(e) => setFileToUpload(e.target.files ? e.target.files[0] : null)} className="w-full" />
          <p className="text-xs text-gray-500 mt-1">Accepted: .md .txt .pdf .docx .yaml .yml .json .tf</p>
        </div>
      )}

      <div className="flex gap-2">
        <button type="submit" disabled={saving || !name} className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm hover:bg-brand-700 disabled:opacity-50">
          {saving ? 'Creating…' : 'Create Source'}
        </button>
        <button type="button" onClick={onCreated} className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">Cancel</button>
      </div>
    </form>
  );
}


// ── Search Panel ────────────────────────────────────────────────────────

function SearchPanel() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<KnowledgeSearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    try {
      const res = await knowledgeApi.search(query);
      setResults(res.data.results);
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Search failed');
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="bg-white rounded-lg border p-5 space-y-4">
      <h4 className="font-medium text-gray-800 flex items-center gap-2">
        <Search className="h-4 w-4" /> Search Knowledge Base
      </h4>
      <div className="flex gap-2">
        <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleSearch()} placeholder="Search across all knowledge sources…" className="flex-1 border rounded-lg px-3 py-2 text-sm" />
        <button onClick={handleSearch} disabled={searching || !query.trim()} className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm hover:bg-brand-700 disabled:opacity-50">
          {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Search'}
        </button>
      </div>

      {results.length > 0 && (
        <div className="space-y-3">
          {results.map((r, i) => (
            <div key={i} className="border rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <Badge type={r.source_type} />
                <span className="font-medium text-sm text-gray-800">{r.document_title}</span>
                <span className="ml-auto text-xs text-gray-400">Score: {r.score.toFixed(2)}</span>
              </div>
              <p className="text-sm text-gray-600 whitespace-pre-wrap line-clamp-4">{r.chunk_content}</p>
              <div className="flex items-center gap-3 mt-1 text-xs text-gray-400">
                <span>{r.source_name}</span>
                {r.file_path && <span>{r.file_path}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
