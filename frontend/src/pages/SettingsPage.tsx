import { useEffect, useState } from 'react';
import api from '../api/client';
import { Save, Send, Zap, X, Eye, EyeOff, Mail, Bell, Globe, Link, Shield, CheckCircle, XCircle, Database, Lock } from 'lucide-react';

interface AppSetting {
  key: string;
  value: string;
  category: string;
  description: string | null;
  is_secret: string;
}

interface TestResult {
  success: boolean;
  message: string;
}

const CATEGORIES = [
  { id: 'smtp', label: 'SMTP / Email', icon: Mail, description: 'Configure outgoing email for alert notifications' },
  { id: 'notifications', label: 'Notifications', icon: Bell, description: 'Control when and where notifications are sent' },
  { id: 'general', label: 'General', icon: Globe, description: 'Application-wide settings' },
  { id: 'integrations', label: 'Integrations', icon: Link, description: 'Slack, Teams, and webhook configuration' },
  { id: 'auth', label: 'Authentication / MFA', icon: Lock, description: 'Local login, SSO, and multi-factor authentication settings' },
  { id: 'rag', label: 'Knowledge Base (RAG)', icon: Database, description: 'Retrieval-Augmented Generation — embed documents and enhance AI analysis with relevant context' },
  { id: 'security', label: 'Security / Key Vault', icon: Shield, description: 'Azure Key Vault integration for secret management' },
];

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSetting[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [smtpTestEmail, setSmtpTestEmail] = useState('');
  const [activeTab, setActiveTab] = useState('smtp');
  const [kvStatus, setKvStatus] = useState<{ connected: boolean; vault_url?: string; error?: string } | null>(null);
  const [kvLoading, setKvLoading] = useState(false);

  const fetchSettings = () => {
    setLoading(true);
    api.get('/settings/')
      .then((res) => {
        setSettings(res.data);
        const formData: Record<string, string> = {};
        res.data.forEach((s: AppSetting) => { formData[s.key] = s.value; });
        setForm(formData);
        setDirty(false);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchSettings(); }, []);

  const handleChange = (key: string, value: string) => {
    setForm({ ...form, [key]: value });
    setDirty(true);
    setSaveMsg(null);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      const res = await api.put('/settings/', { settings: form });
      setSettings(res.data);
      const formData: Record<string, string> = {};
      res.data.forEach((s: AppSetting) => { formData[s.key] = s.value; });
      setForm(formData);
      setDirty(false);
      setSaveMsg({ type: 'success', text: 'Settings saved successfully' });
    } catch (err: any) {
      setSaveMsg({ type: 'error', text: err.response?.data?.detail || 'Failed to save settings' });
    } finally {
      setSaving(false);
    }
  };

  const handleTestSMTP = async () => {
    if (!smtpTestEmail) return;
    setTesting('smtp');
    setTestResult(null);
    try {
      const res = await api.post('/settings/test-smtp', { to_email: smtpTestEmail });
      setTestResult(res.data);
    } catch (err: any) {
      setTestResult({ success: false, message: err.response?.data?.detail || 'SMTP test failed' });
    } finally {
      setTesting(null);
    }
  };

  const handleTestSlack = async () => {
    setTesting('slack');
    setTestResult(null);
    try {
      const res = await api.post('/settings/test-slack');
      setTestResult(res.data);
    } catch (err: any) {
      setTestResult({ success: false, message: err.response?.data?.detail || 'Slack test failed' });
    } finally {
      setTesting(null);
    }
  };

  const handleTestTeams = async () => {
    setTesting('teams');
    setTestResult(null);
    try {
      const res = await api.post('/settings/test-teams');
      setTestResult(res.data);
    } catch (err: any) {
      setTestResult({ success: false, message: err.response?.data?.detail || 'Teams test failed' });
    } finally {
      setTesting(null);
    }
  };

  const handleKvStatus = async () => {
    setKvLoading(true);
    setKvStatus(null);
    try {
      const res = await api.get('/settings/keyvault/status');
      setKvStatus(res.data);
    } catch (err: any) {
      setKvStatus({ connected: false, error: err.response?.data?.detail || 'Failed to check status' });
    } finally {
      setKvLoading(false);
    }
  };

  const handleKvTest = async () => {
    setTesting('keyvault');
    setTestResult(null);
    try {
      const res = await api.post('/settings/keyvault/test');
      setTestResult(res.data);
    } catch (err: any) {
      setTestResult({ success: false, message: err.response?.data?.detail || 'Key Vault test failed' });
    } finally {
      setTesting(null);
    }
  };

  const toggleSecret = (key: string) => {
    setShowSecrets({ ...showSecrets, [key]: !showSecrets[key] });
  };

  const categorySettings = (cat: string) => settings.filter((s) => s.category === cat);

  const renderField = (s: AppSetting) => {
    const isSecret = s.is_secret === 'true';
    const BOOL_KEYS = new Set(['auto_analyze', 'smtp_use_tls', 'rag_enabled', 'auth_local_enabled']);
    const isBool = s.key.startsWith('notify_on_') || BOOL_KEYS.has(s.key);
    const NUMBER_KEYS = new Set([
      'smtp_port', 'alert_retention_days', 'mfa_otp_expiry_seconds',
      'rag_chunk_size', 'rag_chunk_overlap', 'rag_top_k',
    ]);
    const TEXTAREA_KEYS = new Set(['notify_recipients', 'cors_origins']);
    const value = form[s.key] ?? '';

    if (isBool) {
      return (
        <div key={s.key} className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
          <div>
            <p className="text-sm font-medium text-gray-700">{s.description || s.key}</p>
            <p className="text-xs text-gray-400">{s.key}</p>
          </div>
          <button
            type="button"
            onClick={() => handleChange(s.key, value === 'true' ? 'false' : 'true')}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${value === 'true' ? 'bg-brand-500' : 'bg-gray-300'}`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${value === 'true' ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
        </div>
      );
    }

    return (
      <div key={s.key} className="py-3 border-b border-gray-100 last:border-0">
        <label className="block text-sm font-medium text-gray-700 mb-1">{s.description || s.key}</label>
        <div className="relative">
          {s.key === 'ai_mode' ? (
            <select
              className="input-field"
              value={value}
              onChange={(e) => handleChange(s.key, e.target.value)}
            >
              <option value="builtin">Built-in (OpenAI / Anthropic / Gemini)</option>
              <option value="azure_foundry">Azure AI Foundry</option>
            </select>
          ) : NUMBER_KEYS.has(s.key) ? (
            <input
              type="number"
              className="input-field"
              value={value}
              onChange={(e) => handleChange(s.key, e.target.value)}
            />
          ) : TEXTAREA_KEYS.has(s.key) ? (
            <textarea
              className="input-field"
              rows={2}
              value={value}
              onChange={(e) => handleChange(s.key, e.target.value)}
              placeholder={s.key === 'cors_origins' ? 'https://app.example.com,https://admin.example.com' : 'email1@example.com, email2@example.com'}
            />
          ) : s.key === 'rag_score_threshold' ? (
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              className="input-field"
              value={value}
              onChange={(e) => handleChange(s.key, e.target.value)}
            />
          ) : (
            <input
              type={isSecret && !showSecrets[s.key] ? 'password' : 'text'}
              className={`input-field ${isSecret ? 'pr-10' : ''}`}
              value={value}
              onChange={(e) => handleChange(s.key, e.target.value)}
              placeholder={isSecret ? '••••••••' : ''}
            />
          )}
          {isSecret && (
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2"
              onClick={() => toggleSecret(s.key)}
            >
              {showSecrets[s.key] ? <EyeOff className="h-4 w-4 text-gray-400" /> : <Eye className="h-4 w-4 text-gray-400" />}
            </button>
          )}
        </div>
        <p className="text-xs text-gray-400 mt-0.5">{s.key}</p>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <div className="animate-spin h-8 w-8 border-4 border-brand-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-lg font-semibold text-gray-800">Settings</h3>
          <p className="text-sm text-gray-500 mt-1">Configure SMTP, notifications, integrations, and general application settings</p>
        </div>
        <button
          onClick={handleSave}
          disabled={!dirty || saving}
          className="btn-primary flex items-center gap-2 disabled:opacity-50"
        >
          <Save className="h-4 w-4" />
          {saving ? 'Saving...' : 'Save All'}
        </button>
      </div>

      {/* Feedback banners */}
      {saveMsg && (
        <div className={`mb-4 rounded-lg px-4 py-3 text-sm flex justify-between ${saveMsg.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
          {saveMsg.text}
          <button onClick={() => setSaveMsg(null)}><X className="h-4 w-4" /></button>
        </div>
      )}
      {testResult && (
        <div className={`mb-4 rounded-lg px-4 py-3 text-sm flex justify-between ${testResult.success ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
          {testResult.message}
          <button onClick={() => setTestResult(null)}><X className="h-4 w-4" /></button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b border-gray-200 overflow-x-auto">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.id}
            onClick={() => setActiveTab(cat.id)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
              activeTab === cat.id
                ? 'border-brand-500 text-brand-500'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <cat.icon className="h-4 w-4" />
            {cat.label}
          </button>
        ))}
      </div>

      {/* Active tab content */}
      {CATEGORIES.filter((cat) => cat.id === activeTab).map((cat) => (
        <div key={cat.id} className="card">
          <div className="mb-4">
            <h3 className="text-lg font-semibold text-gray-800 flex items-center gap-2">
              <cat.icon className="h-5 w-5 text-brand-500" />
              {cat.label}
            </h3>
            <p className="text-sm text-gray-500">{cat.description}</p>
          </div>

          <div className="divide-y-0">
            {categorySettings(cat.id).map((s) => renderField(s))}
            {categorySettings(cat.id).length === 0 && (
              <p className="text-sm text-gray-400 py-4">No settings in this category</p>
            )}
          </div>

          {/* SMTP test section */}
          {cat.id === 'smtp' && (
            <div className="mt-6 pt-4 border-t border-gray-200">
              <h4 className="text-sm font-medium text-gray-700 mb-2">Test SMTP Connection</h4>
              <p className="text-xs text-gray-400 mb-3">Save settings first, then send a test email to verify configuration.</p>
              <div className="flex gap-2">
                <input
                  type="email"
                  className="input-field flex-1"
                  placeholder="test@example.com"
                  value={smtpTestEmail}
                  onChange={(e) => setSmtpTestEmail(e.target.value)}
                />
                <button
                  onClick={handleTestSMTP}
                  disabled={testing === 'smtp' || !smtpTestEmail}
                  className="btn-accent flex items-center gap-2 disabled:opacity-50"
                >
                  <Send className={`h-4 w-4 ${testing === 'smtp' ? 'animate-pulse' : ''}`} />
                  {testing === 'smtp' ? 'Sending...' : 'Send Test'}
                </button>
              </div>
            </div>
          )}

          {/* Integration test buttons */}
          {cat.id === 'integrations' && (
            <div className="mt-6 pt-4 border-t border-gray-200">
              <h4 className="text-sm font-medium text-gray-700 mb-3">Test Integrations</h4>
              <div className="flex gap-2">
                <button
                  onClick={handleTestSlack}
                  disabled={testing === 'slack' || !form.slack_webhook_url}
                  className="btn-accent flex items-center gap-2 text-sm disabled:opacity-50"
                >
                  <Zap className={`h-4 w-4 ${testing === 'slack' ? 'animate-pulse' : ''}`} />
                  {testing === 'slack' ? 'Testing...' : 'Test Slack'}
                </button>
                <button
                  onClick={handleTestTeams}
                  disabled={testing === 'teams' || !form.teams_webhook_url}
                  className="btn-accent flex items-center gap-2 text-sm disabled:opacity-50"
                >
                  <Zap className={`h-4 w-4 ${testing === 'teams' ? 'animate-pulse' : ''}`} />
                  {testing === 'teams' ? 'Testing...' : 'Test Teams'}
                </button>
              </div>
            </div>
          )}

          {/* RAG / Knowledge Base info panel */}
          {cat.id === 'rag' && (
            <div className="mt-4 space-y-4">
              <div className="bg-violet-50 border border-violet-200 rounded-lg px-4 py-3 text-sm text-violet-800">
                <strong>RAG Knowledge Base</strong> lets you embed runbooks, wikis, Jira tickets, and other documents so the AI can retrieve relevant context during alert analysis and chat.
                Enable <code className="bg-violet-100 px-1 py-0.5 rounded text-xs font-mono">rag_enabled</code> above, then go to <strong>Knowledge Base</strong> in the sidebar to add sources and trigger a sync.
              </div>
              <div className="border-t border-gray-200 pt-3">
                <h4 className="text-sm font-medium text-gray-700 mb-2">Quick Reference</h4>
                <ul className="text-xs text-gray-500 space-y-1.5 list-disc pl-4">
                  <li><code className="bg-gray-100 px-1 rounded font-mono">rag_enabled</code> — master switch; all RAG features are disabled when off</li>
                  <li><code className="bg-gray-100 px-1 rounded font-mono">rag_embedding_model</code> — OpenAI embedding model used to vectorize chunks</li>
                  <li><code className="bg-gray-100 px-1 rounded font-mono">rag_chunk_size</code> — token budget per chunk (smaller = more precise, larger = more context)</li>
                  <li><code className="bg-gray-100 px-1 rounded font-mono">rag_top_k</code> — how many chunks are injected per AI request</li>
                  <li><code className="bg-gray-100 px-1 rounded font-mono">rag_score_threshold</code> — minimum cosine similarity; raise to 0.8+ for stricter relevance</li>
                  <li>Requires <code className="bg-gray-100 px-1 rounded font-mono">pgvector</code> extension on PostgreSQL and an OpenAI API key configured in AI Providers</li>
                </ul>
              </div>
            </div>
          )}

          {/* Security / Key Vault section */}
          {cat.id === 'security' && (
            <div className="space-y-6">
              <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 text-sm text-blue-800">
                <strong>Azure Key Vault</strong> securely stores application secrets (API keys, passwords, tokens) instead of encrypted values in the database.
                Set the <code className="bg-blue-100 px-1 py-0.5 rounded text-xs font-mono">AZURE_KEY_VAULT_URL</code> environment variable to enable.
              </div>

              <div className="space-y-3">
                <h4 className="text-sm font-medium text-gray-700">Connection Status</h4>
                {kvStatus ? (
                  <div className={`rounded-lg px-4 py-3 text-sm flex items-center gap-3 ${kvStatus.connected ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-800'}`}>
                    {kvStatus.connected ? <CheckCircle className="h-5 w-5 flex-shrink-0" /> : <XCircle className="h-5 w-5 flex-shrink-0" />}
                    <div>
                      <p className="font-medium">{kvStatus.connected ? 'Connected' : 'Not Connected'}</p>
                      {kvStatus.vault_url && <p className="text-xs mt-0.5">Vault: {kvStatus.vault_url}</p>}
                      {kvStatus.error && <p className="text-xs mt-0.5">{kvStatus.error}</p>}
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-gray-400">Click "Check Status" to verify Key Vault connectivity</p>
                )}
                <div className="flex gap-2">
                  <button
                    onClick={handleKvStatus}
                    disabled={kvLoading}
                    className="btn-secondary flex items-center gap-2 text-sm disabled:opacity-50"
                  >
                    <Shield className={`h-4 w-4 ${kvLoading ? 'animate-pulse' : ''}`} />
                    {kvLoading ? 'Checking...' : 'Check Status'}
                  </button>
                  <button
                    onClick={handleKvTest}
                    disabled={testing === 'keyvault'}
                    className="btn-accent flex items-center gap-2 text-sm disabled:opacity-50"
                  >
                    <Zap className={`h-4 w-4 ${testing === 'keyvault' ? 'animate-pulse' : ''}`} />
                    {testing === 'keyvault' ? 'Testing...' : 'Test Read/Write'}
                  </button>
                </div>
              </div>

              <div className="border-t border-gray-200 pt-4">
                <h4 className="text-sm font-medium text-gray-700 mb-2">How It Works</h4>
                <ul className="text-xs text-gray-500 space-y-1.5 list-disc pl-4">
                  <li>When Key Vault is enabled, new secrets (API keys, passwords, tokens) are stored in Azure Key Vault</li>
                  <li>The database stores only a <code className="bg-gray-100 px-1 rounded font-mono">kv://secret-name</code> reference</li>
                  <li>Existing Fernet-encrypted secrets continue to work (backward compatible)</li>
                  <li>If Key Vault is unavailable, secrets fall back to local Fernet encryption</li>
                  <li>Requires <code className="bg-gray-100 px-1 rounded font-mono">AZURE_KEY_VAULT_URL</code>, <code className="bg-gray-100 px-1 rounded font-mono">AZURE_TENANT_ID</code>, <code className="bg-gray-100 px-1 rounded font-mono">AZURE_CLIENT_ID</code>, <code className="bg-gray-100 px-1 rounded font-mono">AZURE_CLIENT_SECRET</code></li>
                </ul>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
