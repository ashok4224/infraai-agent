import { useEffect, useState } from 'react';
import api from '../api/client';
import { Plus, Pencil, Trash2, Shield, Users, ChevronDown, ChevronRight, Check, ShieldCheck } from 'lucide-react';
import clsx from 'clsx';

interface Permission {
  id: string;
  name: string;
  display_name: string;
  resource: string;
  action: string;
  description: string | null;
}

interface AppRole {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  is_system: boolean;
  mfa_required: boolean;
  permissions: Permission[];
}

interface UserWithRoles {
  user_id: string;
  email: string;
  full_name: string;
  system_role: string;
  custom_roles: AppRole[];
}

const RESOURCE_LABELS: Record<string, string> = {
  alerts: '🔔 Alerts',
  users: '👤 Users',
  servers: '🖥 Servers / SSH',
  db_explorer: '🗄 DB Explorer',
  ai_config: '🤖 AI Config',
  agent_profiles: '🧠 Agent Profiles',
  mcp_config: '🔌 MCP / Oracle',
  settings: '⚙️ Settings',
  roles: '🔐 Roles & RBAC',
};

export default function RolesPage() {
  const [tab, setTab] = useState<'roles' | 'assignments'>('roles');

  // ── Roles & Permissions state ────────────────────────────────────────────
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [roles, setRoles] = useState<AppRole[]>([]);
  const [expandedRole, setExpandedRole] = useState<string | null>(null);
  const [showRoleModal, setShowRoleModal] = useState(false);
  const [editRole, setEditRole] = useState<AppRole | null>(null);
  const [roleForm, setRoleForm] = useState({ name: '', display_name: '', description: '' });
  const [selectedPermIds, setSelectedPermIds] = useState<Set<string>>(new Set());
  const [roleSaveError, setRoleSaveError] = useState<string | null>(null);
  const [savingRole, setSavingRole] = useState(false);

  // ── User assignment state ────────────────────────────────────────────────
  const [users, setUsers] = useState<UserWithRoles[]>([]);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [draftRoleIds, setDraftRoleIds] = useState<Set<string>>(new Set());
  const [savingUser, setSavingUser] = useState(false);

  const fetchAll = () => {
    api.get('/rbac/permissions').then(r => setPermissions(r.data));
    api.get('/rbac/roles').then(r => setRoles(r.data));
  };
  const fetchUsers = () => api.get('/rbac/users').then(r => setUsers(r.data));

  useEffect(() => { fetchAll(); fetchUsers(); }, []);

  // Group permissions by resource
  const permsByResource = permissions.reduce((acc, p) => {
    if (!acc[p.resource]) acc[p.resource] = [];
    acc[p.resource].push(p);
    return acc;
  }, {} as Record<string, Permission[]>);

  // ── Role Modal helpers ───────────────────────────────────────────────────
  const openCreate = () => {
    setEditRole(null);
    setRoleForm({ name: '', display_name: '', description: '' });
    setSelectedPermIds(new Set());
    setRoleSaveError(null);
    setShowRoleModal(true);
  };

  const openEdit = (role: AppRole) => {
    setEditRole(role);
    setRoleForm({ name: role.name, display_name: role.display_name, description: role.description || '' });
    setSelectedPermIds(new Set(role.permissions.map(p => p.id)));
    setRoleSaveError(null);
    setShowRoleModal(true);
  };

  const togglePerm = (id: string) =>
    setSelectedPermIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleResource = (resource: string) => {
    const ids = (permsByResource[resource] || []).map(p => p.id);
    const allSelected = ids.every(id => selectedPermIds.has(id));
    setSelectedPermIds(prev => {
      const next = new Set(prev);
      ids.forEach(id => allSelected ? next.delete(id) : next.add(id));
      return next;
    });
  };

  const handleSaveRole = async () => {
    setSavingRole(true);
    setRoleSaveError(null);
    const payload = {
      name: roleForm.name,
      display_name: roleForm.display_name,
      description: roleForm.description || null,
      permission_ids: [...selectedPermIds],
    };
    try {
      if (editRole) {
        await api.patch(`/rbac/roles/${editRole.id}`, { ...payload, name: undefined });
      } else {
        await api.post('/rbac/roles', payload);
      }
      setShowRoleModal(false);
      fetchAll();
    } catch (err: any) {
      setRoleSaveError(err.response?.data?.detail || err.message);
    } finally {
      setSavingRole(false);
    }
  };

  const handleDeleteRole = async (id: string) => {
    if (!confirm('Delete this role? Users with this role will lose it.')) return;
    try {
      await api.delete(`/rbac/roles/${id}`);
      fetchAll();
    } catch (err: any) {
      alert(err.response?.data?.detail || err.message);
    }
  };

  // ── User assignment helpers ──────────────────────────────────────────────
  const openUserEdit = (u: UserWithRoles) => {
    setEditingUserId(u.user_id);
    setDraftRoleIds(new Set(u.custom_roles.map(r => r.id)));
  };

  const toggleUserRole = (roleId: string) =>
    setDraftRoleIds(prev => {
      const next = new Set(prev);
      next.has(roleId) ? next.delete(roleId) : next.add(roleId);
      return next;
    });

  const handleSaveUserRoles = async (userId: string) => {
    setSavingUser(true);
    try {
      await api.put(`/rbac/users/${userId}/roles`, { role_ids: [...draftRoleIds] });
      fetchUsers();
      setEditingUserId(null);
    } catch (err: any) {
      alert(err.response?.data?.detail || err.message);
    } finally {
      setSavingUser(false);
    }
  };

  const SYSTEM_ROLE_BADGE: Record<string, string> = {
    admin: 'bg-red-100 text-red-700',
    operator: 'bg-orange-100 text-orange-700',
    viewer: 'bg-gray-100 text-gray-600',
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900">Roles & Permissions</h3>
        <p className="text-sm text-gray-500 mt-1">
          Define custom roles with fine-grained permission sets, then assign them to users.
          System roles (admin, operator, viewer) mirror built-in access levels and cannot be modified.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {(['roles', 'assignments'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              'px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors',
              tab === t
                ? 'border-brand-500 text-brand-600'
                : 'border-transparent text-gray-500 hover:text-gray-700',
            )}
          >
            {t === 'roles' ? <><Shield className="inline h-4 w-4 mr-1.5 -mt-0.5" />Roles & Permissions</> : <><Users className="inline h-4 w-4 mr-1.5 -mt-0.5" />User Assignments</>}
          </button>
        ))}
      </div>

      {/* ── ROLES TAB ──────────────────────────────────────────────────────── */}
      {tab === 'roles' && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <button onClick={openCreate} className="btn-primary flex items-center gap-2">
              <Plus className="h-4 w-4" /> New Role
            </button>
          </div>

          {roles.map(role => (
            <div key={role.id} className="card">
              <div
                className="flex items-start justify-between cursor-pointer"
                onClick={() => setExpandedRole(expandedRole === role.id ? null : role.id)}
              >
                <div className="flex items-center gap-3">
                  {expandedRole === role.id
                    ? <ChevronDown className="h-4 w-4 text-gray-400 flex-shrink-0" />
                    : <ChevronRight className="h-4 w-4 text-gray-400 flex-shrink-0" />}
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-gray-800">{role.display_name}</span>
                      <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded text-gray-500">{role.name}</code>
                      {role.is_system && <span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full">system</span>}
                      {role.mfa_required && <span className="text-xs bg-amber-50 text-amber-700 px-2 py-0.5 rounded-full flex items-center gap-0.5"><ShieldCheck className="h-3 w-3" />MFA enforced</span>}
                    </div>
                    {role.description && <p className="text-sm text-gray-500 mt-0.5">{role.description}</p>}
                    <p className="text-xs text-gray-400 mt-1">{role.permissions.length} permission{role.permissions.length !== 1 ? 's' : ''}</p>
                  </div>
                </div>
                {!role.is_system && (
                  <div className="flex gap-2 flex-shrink-0" onClick={e => e.stopPropagation()}>
                    <button
                      onClick={async () => { await api.patch(`/mfa/roles/${role.id}`, { mfa_required: !role.mfa_required }); fetchAll(); }}
                      className={`text-sm flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border transition-colors ${
                        role.mfa_required
                          ? 'border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100'
                          : 'border-gray-200 text-gray-500 hover:bg-gray-50'
                      }`}
                      title={role.mfa_required ? 'Disable MFA enforcement' : 'Enable MFA enforcement'}
                    >
                      <ShieldCheck className="h-3.5 w-3.5" />{role.mfa_required ? 'MFA On' : 'MFA Off'}
                    </button>
                    <button onClick={() => openEdit(role)} className="btn-secondary text-sm flex items-center gap-1.5">
                      <Pencil className="h-3.5 w-3.5" />Edit
                    </button>
                    <button onClick={() => handleDeleteRole(role.id)} className="text-red-500 hover:text-red-700 p-1.5 rounded-lg hover:bg-red-50">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                )}
              </div>

              {expandedRole === role.id && (
                <div className="mt-4 pt-4 border-t border-gray-100">
                  {Object.entries(permsByResource).map(([resource, perms]) => {
                    const granted = perms.filter(p => role.permissions.some(rp => rp.id === p.id));
                    if (granted.length === 0) return null;
                    return (
                      <div key={resource} className="mb-3">
                        <p className="text-xs font-semibold text-gray-500 mb-1.5">{RESOURCE_LABELS[resource] || resource}</p>
                        <div className="flex flex-wrap gap-1.5">
                          {granted.map(p => (
                            <span key={p.id} className="inline-flex items-center gap-1 text-xs bg-green-50 text-green-700 px-2 py-1 rounded-full">
                              <Check className="h-3 w-3" />{p.display_name}
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                  {role.permissions.length === 0 && <p className="text-sm text-gray-400">No permissions assigned.</p>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── ASSIGNMENTS TAB ────────────────────────────────────────────────── */}
      {tab === 'assignments' && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-3 px-3 font-medium text-gray-500">User</th>
                <th className="text-left py-3 px-3 font-medium text-gray-500">System Role</th>
                <th className="text-left py-3 px-3 font-medium text-gray-500">Custom Roles</th>
                <th className="text-right py-3 px-3 font-medium text-gray-500">Action</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <>
                  <tr key={u.user_id} className="border-b border-gray-100">
                    <td className="py-3 px-3">
                      <p className="font-medium text-gray-800">{u.full_name}</p>
                      <p className="text-xs text-gray-400">{u.email}</p>
                    </td>
                    <td className="py-3 px-3">
                      <span className={`badge ${SYSTEM_ROLE_BADGE[u.system_role] || 'bg-gray-100 text-gray-600'}`}>
                        {u.system_role}
                      </span>
                    </td>
                    <td className="py-3 px-3">
                      {u.custom_roles.length === 0
                        ? <span className="text-gray-400 text-xs">—</span>
                        : (
                          <div className="flex flex-wrap gap-1">
                            {u.custom_roles.map(r => (
                              <span key={r.id} className="text-xs bg-brand-50 text-brand-700 px-2 py-0.5 rounded-full">{r.display_name}</span>
                            ))}
                          </div>
                        )}
                    </td>
                    <td className="py-3 px-3 text-right">
                      <button onClick={() => openUserEdit(u)} className="btn-secondary text-sm flex items-center gap-1.5 ml-auto">
                        <Pencil className="h-3.5 w-3.5" />Assign Roles
                      </button>
                    </td>
                  </tr>
                  {editingUserId === u.user_id && (
                    <tr key={`${u.user_id}-edit`} className="bg-gray-50">
                      <td colSpan={4} className="px-3 py-4">
                        <div className="space-y-3">
                          <p className="text-sm font-medium text-gray-700">
                            Assign custom roles to <strong>{u.full_name}</strong>
                            <span className="text-xs text-gray-400 ml-2">(system role <em>{u.system_role}</em> is unchanged)</span>
                          </p>
                          <div className="flex flex-wrap gap-2">
                            {roles.map(role => (
                              <label key={role.id} className="flex items-center gap-2 cursor-pointer bg-white border border-gray-200 rounded-lg px-3 py-2 hover:border-brand-300 transition-colors">
                                <input
                                  type="checkbox"
                                  checked={draftRoleIds.has(role.id)}
                                  onChange={() => toggleUserRole(role.id)}
                                  className="rounded"
                                />
                                <span className="text-sm font-medium">{role.display_name}</span>
                                {role.is_system && <span className="text-xs text-blue-500">(system)</span>}
                              </label>
                            ))}
                          </div>
                          <div className="flex gap-2">
                            <button onClick={() => handleSaveUserRoles(u.user_id)} disabled={savingUser} className="btn-primary text-sm disabled:opacity-50">
                              {savingUser ? 'Saving…' : 'Save'}
                            </button>
                            <button onClick={() => setEditingUserId(null)} className="btn-secondary text-sm">Cancel</button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Role Create/Edit Modal ──────────────────────────────────────────── */}
      {showRoleModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-black/40 flex items-start justify-center pt-8 pb-8">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl mx-4">
            <div className="flex justify-between items-center px-6 py-4 border-b">
              <h2 className="text-lg font-semibold text-gray-800">{editRole ? 'Edit Role' : 'Create Role'}</h2>
              <button onClick={() => setShowRoleModal(false)} className="text-gray-400 hover:text-gray-600 text-2xl">×</button>
            </div>
            <div className="p-6 space-y-5 max-h-[75vh] overflow-y-auto">

              {/* Name / display name */}
              <div className="grid grid-cols-2 gap-4">
                {!editRole && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Role Name (slug) *</label>
                    <input
                      className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm"
                      value={roleForm.name}
                      onChange={e => setRoleForm(f => ({ ...f, name: e.target.value.toLowerCase().replace(/\s+/g, '_') }))}
                      placeholder="oracle_dba"
                    />
                  </div>
                )}
                <div className={editRole ? 'col-span-2' : ''}>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Display Name *</label>
                  <input
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm"
                    value={roleForm.display_name}
                    onChange={e => setRoleForm(f => ({ ...f, display_name: e.target.value }))}
                    placeholder="Oracle DBA"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                  <input
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm"
                    value={roleForm.description}
                    onChange={e => setRoleForm(f => ({ ...f, description: e.target.value }))}
                    placeholder="Access for Oracle DBA team members"
                  />
                </div>
              </div>

              {/* Permissions Matrix */}
              <div>
                <p className="text-sm font-semibold text-gray-700 mb-3">Permissions</p>
                <div className="space-y-4">
                  {Object.entries(permsByResource).map(([resource, perms]) => {
                    const allSelected = perms.every(p => selectedPermIds.has(p.id));
                    const someSelected = perms.some(p => selectedPermIds.has(p.id));
                    return (
                      <div key={resource} className="border border-gray-200 rounded-lg p-3">
                        <label className="flex items-center gap-2 cursor-pointer mb-2">
                          <input
                            type="checkbox"
                            checked={allSelected}
                            ref={el => { if (el) el.indeterminate = someSelected && !allSelected; }}
                            onChange={() => toggleResource(resource)}
                            className="rounded"
                          />
                          <span className="text-sm font-medium text-gray-700">{RESOURCE_LABELS[resource] || resource}</span>
                        </label>
                        <div className="ml-5 flex flex-wrap gap-2">
                          {perms.map(p => (
                            <label key={p.id} className="flex items-center gap-1.5 cursor-pointer text-xs text-gray-600">
                              <input
                                type="checkbox"
                                checked={selectedPermIds.has(p.id)}
                                onChange={() => togglePerm(p.id)}
                                className="rounded"
                              />
                              {p.display_name}
                            </label>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-3 px-6 py-4 border-t bg-gray-50 rounded-b-xl">
              <button onClick={() => setShowRoleModal(false)} className="btn-secondary">Cancel</button>
              {roleSaveError && <p className="flex-1 text-sm text-red-600 self-center">{roleSaveError}</p>}
              <button
                onClick={handleSaveRole}
                disabled={savingRole || !roleForm.display_name || (!editRole && !roleForm.name)}
                className="btn-primary disabled:opacity-50"
              >
                {savingRole ? 'Saving…' : editRole ? 'Update Role' : 'Create Role'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
