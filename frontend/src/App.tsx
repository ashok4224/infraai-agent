import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import MainLayout from './layouts/MainLayout';
import LoginPage from './pages/LoginPage';
import SSOCallbackPage from './pages/SSOCallbackPage';
import DashboardPage from './pages/DashboardPage';
import AlertsPage from './pages/AlertsPage';
import AlertDetailPage from './pages/AlertDetailPage';
import UsersPage from './pages/UsersPage';
import DBExplorerPage from './pages/DBExplorerPage';
import SystemConfigPage from './pages/SystemConfigPage';
import AskMePage from './pages/AskMePage';
import FoundryConfigPage from './pages/FoundryConfigPage';
import CommandApprovalPage from './pages/CommandApprovalPage';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex justify-center items-center h-screen"><div className="animate-spin h-8 w-8 border-4 border-brand-500 border-t-transparent rounded-full" /></div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (user?.role !== 'admin') return <Navigate to="/" replace />;
  return <>{children}</>;
}

function OperatorRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (user?.role !== 'admin' && user?.role !== 'operator') return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/sso/callback" element={<SSOCallbackPage />} />
      <Route path="/" element={<ProtectedRoute><MainLayout /></ProtectedRoute>}>
        <Route index element={<DashboardPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="alerts/:id" element={<AlertDetailPage />} />
        <Route path="ask-me" element={<AskMePage />} />
        <Route path="db-explorer" element={<DBExplorerPage />} />
        <Route path="command-approvals" element={<OperatorRoute><CommandApprovalPage /></OperatorRoute>} />
        <Route path="users" element={<AdminRoute><UsersPage /></AdminRoute>} />
        <Route path="system-config" element={<OperatorRoute><SystemConfigPage /></OperatorRoute>} />
        <Route path="foundry-config" element={<AdminRoute><FoundryConfigPage /></AdminRoute>} />
        {/* Backward-compatible redirects for old bookmarks */}
        <Route path="ai-config" element={<Navigate to="/system-config?tab=ai-providers" replace />} />
        <Route path="agent-profiles" element={<Navigate to="/system-config?tab=agent-profiles" replace />} />
        <Route path="mcp-config" element={<Navigate to="/system-config?tab=mcp-oracle" replace />} />
        <Route path="server-config" element={<Navigate to="/system-config?tab=servers" replace />} />
        <Route path="roles" element={<Navigate to="/system-config?tab=roles" replace />} />
        <Route path="settings" element={<Navigate to="/system-config?tab=settings" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
