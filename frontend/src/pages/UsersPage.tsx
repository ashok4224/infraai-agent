import { useEffect, useState } from 'react';
import api from '../api/client';
import { UserPlus, Pencil, Trash2, X, Check, ShieldCheck } from 'lucide-react';

interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  auth_source: string;
  mfa_enabled: boolean;
  created_at: string;
}

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editUser, setEditUser] = useState<User | null>(null);
  const [form, setForm] = useState({ email: '', full_name: '', password: '', role: 'viewer', is_active: true, mfa_enabled: false });

  const fetchUsers = () => {
    setLoading(true);
    api.get('/users/').then((res) => setUsers(res.data)).finally(() => setLoading(false));
  };

  useEffect(() => { fetchUsers(); }, []);

  const openCreate = () => {
    setEditUser(null);
    setForm({ email: '', full_name: '', password: '', role: 'viewer', is_active: true, mfa_enabled: false });
    setShowModal(true);
  };

  const openEdit = (u: User) => {
    setEditUser(u);
    setForm({ email: u.email, full_name: u.full_name, password: '', role: u.role, is_active: u.is_active, mfa_enabled: u.mfa_enabled });
    setShowModal(true);
  };

  const handleSubmit = async () => {
    if (editUser) {
      await api.patch(`/users/${editUser.id}`, { email: form.email, full_name: form.full_name, role: form.role, is_active: form.is_active });
      // MFA is managed via separate endpoint
      if (form.mfa_enabled !== editUser.mfa_enabled) {
        await api.patch(`/mfa/users/${editUser.id}`, { enabled: form.mfa_enabled });
      }
    } else {
      await api.post('/users/', form);
    }
    setShowModal(false);
    fetchUsers();
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this user?')) return;
    await api.delete(`/users/${id}`);
    fetchUsers();
  };

  const toggleActive = async (u: User) => {
    await api.patch(`/users/${u.id}`, { is_active: !u.is_active });
    fetchUsers();
  };

  const toggleMfa = async (u: User) => {
    await api.patch(`/mfa/users/${u.id}`, { enabled: !u.mfa_enabled });
    fetchUsers();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-gray-800">User Management</h2>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <UserPlus className="h-4 w-4" /> Add User
        </button>
      </div>

      <div className="card overflow-x-auto">
        {loading ? (
          <div className="flex justify-center py-12"><div className="animate-spin h-6 w-6 border-4 border-brand-500 border-t-transparent rounded-full" /></div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-3 px-2 font-medium text-gray-500">Name</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Email</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Role</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Auth</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">MFA</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Active</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Created</th>
                <th className="text-right py-3 px-2 font-medium text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-3 px-2 font-medium text-gray-800">{u.full_name}</td>
                  <td className="py-3 px-2 text-gray-600">{u.email}</td>
                  <td className="py-3 px-2">
                    <span className={`badge ${u.role === 'admin' ? 'badge-critical' : u.role === 'operator' ? 'badge-warning' : 'badge-info'}`}>{u.role}</span>
                  </td>
                  <td className="py-3 px-2">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                      u.auth_source === 'local' ? 'bg-gray-100 text-gray-700' :
                      u.auth_source === 'oidc' ? 'bg-blue-100 text-blue-700' :
                      'bg-purple-100 text-purple-700'
                    }`}>{u.auth_source?.toUpperCase() || 'LOCAL'}</span>
                  </td>
                  <td className="py-3 px-2">
                    {u.mfa_enabled ? (
                      <button onClick={() => toggleMfa(u)} className="inline-flex items-center gap-1 text-green-600 hover:text-green-800" title="Click to disable MFA"><ShieldCheck className="h-4 w-4" /> On</button>
                    ) : (
                      <button onClick={() => toggleMfa(u)} className="text-gray-400 text-xs hover:text-gray-600" title="Click to enable MFA">Off</button>
                    )}
                  </td>
                  <td className="py-3 px-2">
                    <button onClick={() => toggleActive(u)} className={`h-5 w-9 rounded-full transition-colors ${u.is_active ? 'bg-green-500' : 'bg-gray-300'} relative`}>
                      <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${u.is_active ? 'translate-x-4' : 'translate-x-0.5'}`} />
                    </button>
                  </td>
                  <td className="py-3 px-2 text-gray-500">{new Date(u.created_at).toLocaleDateString()}</td>
                  <td className="py-3 px-2 text-right">
                    <button onClick={() => openEdit(u)} className="p-1.5 rounded hover:bg-gray-200"><Pencil className="h-4 w-4 text-gray-500" /></button>
                    <button onClick={() => handleDelete(u.id)} className="p-1.5 rounded hover:bg-red-100 ml-1"><Trash2 className="h-4 w-4 text-red-500" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowModal(false)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">{editUser ? 'Edit User' : 'Create User'}</h3>
              <button onClick={() => setShowModal(false)} className="p-1 rounded hover:bg-gray-100"><X className="h-5 w-5" /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Full Name</label>
                <input className="input-field" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input className="input-field" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </div>
              {!editUser && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                  <input className="input-field" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
                </div>
              )}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
                <select className="input-field" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                  <option value="viewer">Viewer</option>
                  <option value="operator">Operator</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              {editUser && (
                <div className="flex gap-6 pt-2">
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} className="rounded" />
                    Active
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={form.mfa_enabled} onChange={(e) => setForm({ ...form, mfa_enabled: e.target.checked })} className="rounded" />
                    MFA Enabled
                  </label>
                  {editUser.auth_source !== 'local' && (
                    <span className="text-xs text-gray-400 self-center">Auth: {editUser.auth_source.toUpperCase()}</span>
                  )}
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button onClick={() => setShowModal(false)} className="btn-secondary">Cancel</button>
              <button onClick={handleSubmit} className="btn-primary flex items-center gap-1"><Check className="h-4 w-4" /> {editUser ? 'Save' : 'Create'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
