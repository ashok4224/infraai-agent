import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/client';
import { AlertTriangle, CheckCircle, Clock, Activity, ShieldAlert, TrendingUp, Monitor } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

interface Stats {
  total: number;
  firing: number;
  resolved: number;
  analyzed: number;
  pending: number;
  critical: number;
}

interface Alert {
  id: string;
  alertname: string;
  severity: string;
  status: string;
  analysis_status: string;
  instance: string | null;
  received_at: string;
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [recentAlerts, setRecentAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [mcpSummary, setMcpSummary] = useState<any>(null);
  const [trends, setTrends] = useState<any[]>([]);

  useEffect(() => {
    Promise.allSettled([
      api.get('/alerts/stats'),
      api.get('/alerts/?per_page=10'),
      api.get('/alerts/trend?days=7'),
      api.get('/mcp-config/summary')
    ]).then(([statsRes, alertsRes, trendsRes, mcpRes]) => {
      if (statsRes.status === 'fulfilled') setStats(statsRes.value.data);
      if (alertsRes.status === 'fulfilled') setRecentAlerts(alertsRes.value.data.alerts);
      if (trendsRes.status === 'fulfilled') setTrends(trendsRes.value.data);
      if (mcpRes.status === 'fulfilled') setMcpSummary(mcpRes.value.data);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="flex justify-center py-20"><div className="animate-spin h-8 w-8 border-4 border-brand-500 border-t-transparent rounded-full" /></div>;
  }

  const statCards = [
    { label: 'Total Alerts', value: stats?.total ?? 0, icon: Activity, color: 'text-brand-500', bg: 'bg-brand-50' },
    { label: 'Firing', value: stats?.firing ?? 0, icon: AlertTriangle, color: 'text-red-500', bg: 'bg-red-50' },
    { label: 'Resolved', value: stats?.resolved ?? 0, icon: CheckCircle, color: 'text-green-500', bg: 'bg-green-50' },
    { label: 'Analyzed', value: stats?.analyzed ?? 0, icon: TrendingUp, color: 'text-blue-500', bg: 'bg-blue-50' },
    { label: 'Pending', value: stats?.pending ?? 0, icon: Clock, color: 'text-amber-500', bg: 'bg-amber-50' },
    { label: 'Critical', value: stats?.critical ?? 0, icon: ShieldAlert, color: 'text-red-600', bg: 'bg-red-50' },
  ];

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-800 mb-6">Dashboard</h2>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
        {statCards.map((s) => (
          <div key={s.label} className="card flex flex-col items-center text-center py-5">
            <div className={`rounded-full p-2.5 ${s.bg} mb-2`}>
              <s.icon className={`h-5 w-5 ${s.color}`} />
            </div>
            <p className="text-2xl font-bold text-gray-800">{s.value}</p>
            <p className="text-xs text-gray-500 mt-1">{s.label}</p>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-3 gap-6 mb-8">
        <div className="lg:col-span-2 card">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">Alert Trends (Last 7 Days)</h3>
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={trends} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" tick={{fontSize: 12}} tickMargin={10} />
                <YAxis tick={{fontSize: 12}} allowDecimals={false} />
                <Tooltip />
                <Legend />
                <Bar dataKey="critical" name="Critical" stackId="a" fill="#ef4444" radius={[0, 0, 4, 4]} />
                <Bar dataKey="warning" name="Warning" stackId="a" fill="#f59e0b" />
                <Bar dataKey="info" name="Info" stackId="a" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        
        <div className="lg:col-span-1 card">
          <h3 className="text-lg font-semibold text-gray-800 mb-4 flex items-center gap-2">
            <Monitor className="h-5 w-5 text-gray-500" />
            MCP Node Health
          </h3>
          {mcpSummary ? (
            <div className="space-y-4">
              <div className="flex justify-between items-center py-2 border-b border-gray-100">
                <span className="text-gray-600 font-medium">Total Configured</span>
                <span className="font-bold text-gray-900">{mcpSummary.total}</span>
              </div>
              <div className="flex justify-between items-center py-2 border-b border-gray-100">
                <div className="flex items-center gap-2">
                  <div className="h-3 w-3 rounded-full bg-green-500"></div>
                  <span className="text-gray-600">Healthy</span>
                </div>
                <span className="font-semibold text-gray-800">{mcpSummary.healthy}</span>
              </div>
              <div className="flex justify-between items-center py-2 border-b border-gray-100">
                <div className="flex items-center gap-2">
                  <div className="h-3 w-3 rounded-full bg-red-500"></div>
                  <span className="text-gray-600">Unhealthy</span>
                </div>
                <span className="font-semibold text-gray-800">{mcpSummary.unhealthy}</span>
              </div>
              <div className="flex justify-between items-center py-2">
                <div className="flex items-center gap-2">
                  <div className="h-3 w-3 rounded-full bg-amber-500"></div>
                  <span className="text-gray-600">Unreachable/Unknown</span>
                </div>
                <span className="font-semibold text-gray-800">{mcpSummary.unreachable + mcpSummary.unknown}</span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500">No MCP data available.</p>
          )}
        </div>
      </div>

      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800">Recent Alerts</h3>
          <Link to="/alerts" className="text-sm text-brand-500 hover:text-brand-600 font-medium">
            View All →
          </Link>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-3 px-2 font-medium text-gray-500">Alert</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Severity</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Status</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Analysis</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Instance</th>
                <th className="text-left py-3 px-2 font-medium text-gray-500">Time</th>
              </tr>
            </thead>
            <tbody>
              {recentAlerts.map((a) => (
                <tr key={a.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-3 px-2">
                    <Link to={`/alerts/${a.id}`} className="text-brand-500 hover:underline font-medium">
                      {a.alertname}
                    </Link>
                  </td>
                  <td className="py-3 px-2">
                    <SeverityBadge severity={a.severity} />
                  </td>
                  <td className="py-3 px-2">
                    <StatusBadge status={a.status} />
                  </td>
                  <td className="py-3 px-2">
                    <AnalysisBadge status={a.analysis_status} />
                  </td>
                  <td className="py-3 px-2 text-gray-600">{a.instance || '—'}</td>
                  <td className="py-3 px-2 text-gray-500 whitespace-nowrap">
                    {new Date(a.received_at).toLocaleString()}
                  </td>
                </tr>
              ))}
              {recentAlerts.length === 0 && (
                <tr><td colSpan={6} className="text-center py-8 text-gray-400">No alerts yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const cls = {
    critical: 'badge-critical',
    warning: 'badge-warning',
    info: 'badge-info',
  }[severity] || 'badge-info';
  return <span className={`badge ${cls}`}>{severity}</span>;
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge ${status === 'firing' ? 'badge-critical' : 'badge-success'}`}>
      {status}
    </span>
  );
}

function AnalysisBadge({ status }: { status: string }) {
  const cls = {
    analyzed: 'badge-success',
    analyzing: 'badge-info',
    pending: 'badge-warning',
    failed: 'badge-critical',
  }[status] || 'badge-warning';
  return <span className={`badge ${cls}`}>{status}</span>;
}
