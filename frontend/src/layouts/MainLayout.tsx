import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
  LayoutDashboard,
  Bell,
  Users,
  LogOut,
  Menu,
  X,
  Shield,
  Search,
  Wrench,
  MessageSquare,
  Cloud,
  ShieldCheck,
} from 'lucide-react';
import { useState, useEffect } from 'react';
import clsx from 'clsx';
import api from '../api/client';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', roles: ['admin', 'operator', 'viewer'] },
  { to: '/alerts', icon: Bell, label: 'Alerts', roles: ['admin', 'operator', 'viewer'] },
  { to: '/ask-me', icon: MessageSquare, label: 'AskMe', roles: ['admin', 'operator', 'viewer'] },
  { to: '/db-explorer', icon: Search, label: 'DB Explorer', roles: ['admin', 'operator'] },
  { to: '/command-approvals', icon: ShieldCheck, label: 'Command Approvals', roles: ['admin', 'operator'] },
  { to: '/users', icon: Users, label: 'Users', roles: ['admin'] },
  { to: '/foundry-config', icon: Cloud, label: 'Foundry Config', roles: ['admin'], modeOnly: 'azure_foundry' as const },
  { to: '/system-config', icon: Wrench, label: 'System Configuration', roles: ['admin', 'operator'] },
];

export default function MainLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [aiMode, setAiMode] = useState<'builtin' | 'azure_foundry'>('builtin');

  useEffect(() => {
    api.get('/settings/').then(r => {
      const modeRow = (r.data as { key: string; value: string }[]).find((s: { key: string }) => s.key === 'ai_mode');
      if (modeRow) setAiMode(modeRow.value as 'builtin' | 'azure_foundry');
    }).catch(() => {});
  }, []);

  const toggleMode = async () => {
    const next = aiMode === 'builtin' ? 'azure_foundry' : 'builtin';
    try {
      await api.put('/settings/', { settings: { ai_mode: next } });
      setAiMode(next);
    } catch { /* ignore */ }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const filteredNav = navItems.filter((item) => {
    if (!user || !item.roles.includes(user.role)) return false;
    if ('modeOnly' in item && item.modeOnly && item.modeOnly !== aiMode) return false;
    return true;
  });

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {/* Sidebar */}
      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-30 w-64 transform bg-brand-500 transition-transform duration-200 ease-in-out lg:relative lg:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-16 items-center gap-3 px-6 border-b border-brand-400">
          <Shield className="h-7 w-7 text-white" />
          <div>
            <h1 className="text-lg font-bold text-white leading-tight">InfraAI Agent</h1>
            <p className="text-[10px] text-brand-200 tracking-widest uppercase">Winfo Solutions</p>
          </div>
        </div>
        <nav className="mt-4 flex flex-col gap-1 px-3">
          {filteredNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-white/15 text-white'
                    : 'text-brand-100 hover:bg-white/10 hover:text-white'
                )
              }
            >
              <item.icon className="h-5 w-5" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-brand-400">
          <div className="flex items-center gap-3 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-white/20 text-white text-sm font-bold">
              {user?.full_name?.[0]?.toUpperCase()}
            </div>
            <div className="overflow-hidden">
              <p className="text-sm font-medium text-white truncate">{user?.full_name}</p>
              <p className="text-xs text-brand-200 truncate">{user?.email}</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-brand-200 hover:bg-white/10 hover:text-white transition-colors"
          >
            <LogOut className="h-4 w-4" />
            Sign Out
          </button>
        </div>
      </aside>

      {/* Overlay for mobile */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-16 items-center justify-between border-b border-gray-200 bg-white px-4 lg:px-8">
          <button
            className="rounded-lg p-2 hover:bg-gray-100 lg:hidden"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            {sidebarOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <span className="hidden sm:inline">Autonomous SRE AI Agent</span>
          </div>
          <div className="flex items-center gap-3">
            {user?.role === 'admin' && (
              <button
                onClick={toggleMode}
                className={clsx(
                  'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors',
                  aiMode === 'builtin'
                    ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'
                    : 'bg-blue-100 text-blue-700 hover:bg-blue-200'
                )}
                title="Click to toggle AI mode"
              >
                {aiMode === 'builtin' ? '⚡ Built-in AI' : '☁️ Azure Foundry'}
              </button>
            )}
            <span className="badge badge-info">{user?.role}</span>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-4 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
