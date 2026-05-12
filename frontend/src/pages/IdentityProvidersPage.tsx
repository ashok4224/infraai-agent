import { useState, useEffect, useCallback } from 'react';
import api from '../api/client';
import {
  Fingerprint, Plus, Pencil, Trash2, X, Check, ToggleLeft, ToggleRight,
  TestTube, Loader2, Star, Shield,
} from 'lucide-react';

interface IDP {
  id: string;
  name: string;
  protocol: string;
  is_active: boolean;
  is_default: boolean;
  oidc_issuer_url: string | null;
  oidc_client_id: string | null;
  oidc_scopes: string | null;
  oidc_redirect_uri: string | null;
  saml_entity_id: string | null;
  saml_idp_metadata_url: string | null;
  saml_acs_url: string | null;
  saml_slo_url: string | null;
  auto_provision: boolean;
  default_role: string;
  group_role_mapping: Record<string, string> | null;
  created_at: string;
  updated_at: string;
}

const EMPTY_FORM: Partial<IDP> & { oidc_client_secret?: string; saml_certificate?: string } = {
  name: '',
  protocol: 'oidc',
  is_active: true,
  is_default: false,
  oidc_issuer_url: '',
  oidc_client_id: '',
  oidc_client_secret: '',
  oidc_scopes: 'openid profile email',
  oidc_redirect_uri: '',
  saml_entity_id: '',
  saml_idp_metadata_url: '',
  saml_acs_url: '',
  saml_slo_url: '',
  saml_certificate: '',
  auto_provision: true,
  default_role: 'viewer',
  group_role_mapping: null,
};

export default function IdentityProvidersPage() {
  const [idps, setIdps] = useState<IDP[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editIdp, setEditIdp] = useState<IDP | null>(null);
  const [form, setForm] = useState<typeof EMPTY_FORM>({ ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [groupMappingText, setGroupMappingText] = useState('');

  const fetchIdps = useCallback(() => {
    setLoading(true);
    api.get('/idp/')
      .then((res) => setIdps(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchIdps(); }, [fetchIdps]);

  const openCreate = () => {
    setEditIdp(null);
    setForm({ ...EMPTY_FORM });
    setGroupMappingText('');
    setError('');
    setShowModal(true);
  };

  const openEdit = (idp: IDP) => {
    setEditIdp(idp);
    setForm({
      name: idp.name,
      protocol: idp.protocol,
      is_active: idp.is_active,
      is_default: idp.is_default,
      oidc_issuer_url: idp.oidc_issuer_url || '',
      oidc_client_id: idp.oidc_client_id || '',
      oidc_client_secret: '', // don't pre-fill secrets
      oidc_scopes: idp.oidc_scopes || 'openid profile email',
      oidc_redirect_uri: idp.oidc_redirect_uri || '',
      saml_entity_id: idp.saml_entity_id || '',
      saml_idp_metadata_url: idp.saml_idp_metadata_url || '',
      saml_acs_url: idp.saml_acs_url || '',
      saml_slo_url: idp.saml_slo_url || '',
      saml_certificate: '',
      auto_provision: idp.auto_provision,
      default_role: idp.default_role,
    });
    setGroupMappingText(
      idp.group_role_mapping ? JSON.stringify(idp.group_role_mapping, null, 2) : ''
    );
    setError('');
    setShowModal(true);
  };

  const handleSubmit = async () => {
    setSaving(true);
    setError('');
    try {
      const payload: any = { ...form };

      // Parse group_role_mapping
      if (groupMappingText.trim()) {
        try {
          payload.group_role_mapping = JSON.parse(groupMappingText);
        } catch {
          setError('Invalid JSON in group-role mapping');
          setSaving(false);
          return;
        }
      } else {
        payload.group_role_mapping = null;
      }

      // Don't send empty secrets (would overwrite existing)
      if (!payload.oidc_client_secret) delete payload.oidc_client_secret;
      if (!payload.saml_certificate) delete payload.saml_certificate;

      if (editIdp) {
        await api.patch(`/idp/${editIdp.id}`, payload);
      } else {
        await api.post('/idp/', payload);
      }
      setShowModal(false);
      fetchIdps();
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this identity provider? Users provisioned from it will keep their accounts but cannot log in via SSO.')) return;
    try {
      await api.delete(`/idp/${id}`);
      fetchIdps();
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Delete failed');
    }
  };

  const handleToggleActive = async (idp: IDP) => {
    try {
      await api.patch(`/idp/${idp.id}`, { is_active: !idp.is_active });
      fetchIdps();
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Toggle failed');
    }
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    setTestResult(null);
    try {
      const res = await api.post(`/idp/${id}/test`);
      setTestResult(JSON.stringify(res.data, null, 2));
    } catch (e: any) {
      setTestResult(`Error: ${e.response?.data?.detail || e.message}`);
    } finally {
      setTesting(null);
    }
  };

  if (loading) {
    return <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-gray-800 flex items-center gap-2">
            <Fingerprint className="h-5 w-5" /> Identity Providers
          </h3>
          <p className="text-sm text-gray-500 mt-1">
            Manage SSO providers (OIDC / SAML) for single sign-on authentication
          </p>
        </div>
        <button onClick={openCreate} className="flex items-center gap-1 px-3 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700">
          <Plus className="h-4 w-4" /> Add Provider
        </button>
      </div>

      {/* Test result banner */}
      {testResult && (
        <div className="bg-gray-50 rounded-lg border p-4 relative">
          <button onClick={() => setTestResult(null)} className="absolute top-2 right-2 p-1 hover:bg-gray-200 rounded"><X className="h-4 w-4" /></button>
          <h4 className="font-medium text-sm mb-2">Connection Test Result</h4>
          <pre className="text-xs bg-white rounded p-3 overflow-auto max-h-40">{testResult}</pre>
        </div>
      )}

      {/* IDP list */}
      {idps.length === 0 ? (
        <div className="bg-white rounded-lg border p-8 text-center text-gray-500">
          <Fingerprint className="h-12 w-12 mx-auto mb-3 text-gray-300" />
          <p>No identity providers configured yet.</p>
          <p className="text-sm">Add an OIDC or SAML provider to enable SSO login.</p>
        </div>
      ) : (
        <div className="grid gap-4">
          {idps.map((idp) => (
            <div key={idp.id} className="bg-white rounded-lg border p-4 hover:shadow-sm transition-shadow">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      idp.protocol === 'oidc' ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700'
                    }`}>{idp.protocol.toUpperCase()}</span>
                    <h4 className="font-medium text-gray-800">{idp.name}</h4>
                    {idp.is_default && <span title="Default provider"><Star className="h-4 w-4 text-yellow-500 fill-yellow-500" /></span>}
                    {!idp.is_active && <span className="text-xs text-gray-400">(disabled)</span>}
                  </div>
                  <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                    {idp.protocol === 'oidc' && idp.oidc_issuer_url && (
                      <span title="Issuer URL">Issuer: {idp.oidc_issuer_url}</span>
                    )}
                    {idp.protocol === 'saml' && idp.saml_entity_id && (
                      <span title="Entity ID">Entity: {idp.saml_entity_id}</span>
                    )}
                    <span>Auto-provision: {idp.auto_provision ? 'Yes' : 'No'}</span>
                    <span>Default role: {idp.default_role}</span>
                    {idp.group_role_mapping && <span>Group mapping: {Object.keys(idp.group_role_mapping).length} rules</span>}
                  </div>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => handleToggleActive(idp)} title={idp.is_active ? 'Disable' : 'Enable'} className="p-1.5 rounded hover:bg-gray-100">
                    {idp.is_active
                      ? <ToggleRight className="h-4 w-4 text-green-500" />
                      : <ToggleLeft className="h-4 w-4 text-gray-400" />}
                  </button>
                  <button onClick={() => handleTest(idp.id)} title="Test connection" disabled={testing === idp.id} className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-40">
                    {testing === idp.id ? <Loader2 className="h-4 w-4 animate-spin text-blue-500" /> : <TestTube className="h-4 w-4 text-blue-500" />}
                  </button>
                  <button onClick={() => openEdit(idp)} title="Edit" className="p-1.5 rounded hover:bg-gray-100">
                    <Pencil className="h-4 w-4 text-gray-500" />
                  </button>
                  <button onClick={() => handleDelete(idp.id)} title="Delete" className="p-1.5 rounded hover:bg-red-50">
                    <Trash2 className="h-4 w-4 text-red-500" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 overflow-y-auto py-8" onClick={() => setShowModal(false)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl mx-4 p-6 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <Shield className="h-5 w-5" /> {editIdp ? 'Edit Identity Provider' : 'Add Identity Provider'}
              </h3>
              <button onClick={() => setShowModal(false)} className="p-1 rounded hover:bg-gray-100"><X className="h-5 w-5" /></button>
            </div>

            {error && <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>}

            <div className="space-y-4">
              {/* Basic */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Provider Name</label>
                  <input className="input-field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Azure AD" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Protocol</label>
                  <select className="input-field" value={form.protocol} onChange={(e) => setForm({ ...form, protocol: e.target.value })} disabled={!!editIdp}>
                    <option value="oidc">OIDC (OpenID Connect)</option>
                    <option value="saml">SAML 2.0</option>
                  </select>
                </div>
              </div>

              <div className="flex gap-6">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} className="rounded" />
                  Active
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={form.is_default} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} className="rounded" />
                  Default provider
                </label>
              </div>

              {/* OIDC Fields */}
              {form.protocol === 'oidc' && (
                <fieldset className="border rounded-lg p-4 space-y-3">
                  <legend className="text-sm font-medium text-gray-700 px-2">OIDC Configuration</legend>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Discovery / Issuer URL</label>
                    <input className="input-field" value={form.oidc_issuer_url || ''} onChange={(e) => setForm({ ...form, oidc_issuer_url: e.target.value })} placeholder="https://login.microsoftonline.com/{tenant}/v2.0" />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm text-gray-600 mb-1">Client ID</label>
                      <input className="input-field" value={form.oidc_client_id || ''} onChange={(e) => setForm({ ...form, oidc_client_id: e.target.value })} />
                    </div>
                    <div>
                      <label className="block text-sm text-gray-600 mb-1">Client Secret</label>
                      <input className="input-field" type="password" value={form.oidc_client_secret || ''} onChange={(e) => setForm({ ...form, oidc_client_secret: e.target.value })} placeholder={editIdp ? '••••••••' : ''} />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm text-gray-600 mb-1">Scopes</label>
                      <input className="input-field" value={form.oidc_scopes || ''} onChange={(e) => setForm({ ...form, oidc_scopes: e.target.value })} />
                    </div>
                    <div>
                      <label className="block text-sm text-gray-600 mb-1">Redirect URI</label>
                      <input className="input-field" value={form.oidc_redirect_uri || ''} onChange={(e) => setForm({ ...form, oidc_redirect_uri: e.target.value })} placeholder="https://yourapp.com/sso/callback" />
                    </div>
                  </div>
                </fieldset>
              )}

              {/* SAML Fields */}
              {form.protocol === 'saml' && (
                <fieldset className="border rounded-lg p-4 space-y-3">
                  <legend className="text-sm font-medium text-gray-700 px-2">SAML Configuration</legend>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">IDP Metadata URL</label>
                    <input className="input-field" value={form.saml_idp_metadata_url || ''} onChange={(e) => setForm({ ...form, saml_idp_metadata_url: e.target.value })} placeholder="https://idp.example.com/metadata" />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm text-gray-600 mb-1">SP Entity ID</label>
                      <input className="input-field" value={form.saml_entity_id || ''} onChange={(e) => setForm({ ...form, saml_entity_id: e.target.value })} />
                    </div>
                    <div>
                      <label className="block text-sm text-gray-600 mb-1">ACS URL</label>
                      <input className="input-field" value={form.saml_acs_url || ''} onChange={(e) => setForm({ ...form, saml_acs_url: e.target.value })} />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">SLO URL (optional)</label>
                    <input className="input-field" value={form.saml_slo_url || ''} onChange={(e) => setForm({ ...form, saml_slo_url: e.target.value })} />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Signing Certificate (PEM)</label>
                    <textarea className="input-field font-mono text-xs" rows={3} value={form.saml_certificate || ''} onChange={(e) => setForm({ ...form, saml_certificate: e.target.value })} placeholder={editIdp ? '(leave blank to keep existing)' : '-----BEGIN CERTIFICATE-----'} />
                  </div>
                </fieldset>
              )}

              {/* Provisioning */}
              <fieldset className="border rounded-lg p-4 space-y-3">
                <legend className="text-sm font-medium text-gray-700 px-2">User Provisioning</legend>
                <div className="flex gap-6">
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.auto_provision} onChange={(e) => setForm({ ...form, auto_provision: e.target.checked })} className="rounded" />
                    Auto-provision new users on first login
                  </label>
                </div>
                <div>
                  <label className="block text-sm text-gray-600 mb-1">Default Role for New Users</label>
                  <select className="input-field w-40" value={form.default_role} onChange={(e) => setForm({ ...form, default_role: e.target.value })}>
                    <option value="viewer">Viewer</option>
                    <option value="operator">Operator</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-gray-600 mb-1">
                    Group → Role Mapping (JSON)
                    <span className="text-gray-400 ml-1">e.g. {`{"InfraAdmins": "admin", "SRE-Team": "operator"}`}</span>
                  </label>
                  <textarea className="input-field font-mono text-xs" rows={3} value={groupMappingText} onChange={(e) => setGroupMappingText(e.target.value)} placeholder='{"GroupName": "role"}' />
                </div>
              </fieldset>
            </div>

            <div className="flex justify-end gap-2 mt-6">
              <button onClick={() => setShowModal(false)} className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">Cancel</button>
              <button onClick={handleSubmit} disabled={saving || !form.name} className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm hover:bg-brand-700 disabled:opacity-50 flex items-center gap-1">
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                {editIdp ? 'Save Changes' : 'Create Provider'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
