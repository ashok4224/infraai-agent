import { Component, ReactNode } from 'react';
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

// ── Error Boundary — catches render crashes and shows a recovery screen ──────
class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 p-8 text-center">
          <div className="h-14 w-14 rounded-full bg-red-100 flex items-center justify-center">
            <span className="text-2xl">⚠️</span>
          </div>
          <h2 className="text-xl font-semibold text-gray-800">Something went wrong</h2>
          <p className="text-sm text-gray-500 max-w-md">{this.state.error.message}</p>
          <button
            onClick={() => { this.setState({ error: null }); window.history.back(); }}
            className="px-4 py-2 rounded-lg bg-brand-500 text-white text-sm font-medium hover:bg-brand-600"
          >
            Go Back
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

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
        <Route index element={<ErrorBoundary><DashboardPage /></ErrorBoundary>} />
        <Route path="alerts" element={<ErrorBoundary><AlertsPage /></ErrorBoundary>} />
        <Route path="alerts/:id" element={<ErrorBoundary><AlertDetailPage /></ErrorBoundary>} />
        <Route path="ask-me" element={<ErrorBoundary><AskMePage /></ErrorBoundary>} />
        <Route path="db-explorer" element={<ErrorBoundary><DBExplorerPage /></ErrorBoundary>} />
        <Route path="command-approvals" element={<OperatorRoute><ErrorBoundary><CommandApprovalPage /></ErrorBoundary></OperatorRoute>} />
        <Route path="users" element={<AdminRoute><ErrorBoundary><UsersPage /></ErrorBoundary></AdminRoute>} />
        <Route path="system-config" element={<OperatorRoute><ErrorBoundary><SystemConfigPage /></ErrorBoundary></OperatorRoute>} />
        <Route path="foundry-config" element={<AdminRoute><ErrorBoundary><FoundryConfigPage /></ErrorBoundary></AdminRoute>} />
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
