import { useState, useEffect } from 'react';
import { Database, Play, AlertCircle, Clock } from 'lucide-react';
import api from '../api/client';

interface Server {
  id: string;
  name: string;
  type: string;
  host: string;
}

export default function DBExplorerPage() {
  const [servers, setServers] = useState<Server[]>([]);
  const [selectedServer, setSelectedServer] = useState<string>('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [execTime, setExecTime] = useState<number | null>(null);

  useEffect(() => {
    api.get('/db-explorer/servers')
      .then(res => {
        setServers(res.data);
        if (res.data.length > 0) setSelectedServer(res.data[0].id);
      })
      .catch(err => {
        console.error("Failed to load servers", err);
      });
  }, []);

  const handleExecute = async () => {
    if (!selectedServer || !query.trim()) return;
    
    setLoading(true);
    setError(null);
    setResults(null);
    setExecTime(null);
    
    try {
      const res = await api.post(`/db-explorer/execute/${selectedServer}`, { sql_query: query });
      if (res.data.success) {
        setResults(res.data.data);
        setExecTime(res.data.execution_time_ms);
      } else {
        setError(res.data.error || "Unknown execution error");
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || "Failed to execute query");
    } finally {
      setLoading(false);
    }
  };

  const getColumns = () => {
    if (!results || results.length === 0) return [];
    // Unpack rows vs objects
    if (results.length > 0 && Array.isArray(results[0])) {
        // We just have raw arrays without column names, maybe return generic
        return results[0].map((_, i) => `Col_${i}`);
    } else if (results.length > 0 && typeof results[0] === 'object') {
        return Object.keys(results[0]);
    }
    return [];
  };

  const renderTable = () => {
    if (!results) return null;
    if (results.length === 0) return <div className="text-gray-500 italic p-4">Query returned 0 rows.</div>;

    const isArrayOfArrays = Array.isArray(results[0]);
    const cols = getColumns();

    return (
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              {cols.map((c, i) => (
                <th key={i} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {results.map((row, i) => (
              <tr key={i} className="hover:bg-gray-50">
                {isArrayOfArrays ? (
                  row.map((val: any, j: number) => (
                    <td key={j} className="px-4 py-2 text-gray-700 whitespace-nowrap">
                      {String(val ?? 'NULL')}
                    </td>
                  ))
                ) : (
                  cols.map((col: string, j: number) => (
                    <td key={j} className="px-4 py-2 text-gray-700 whitespace-nowrap">
                      {String(row[col] ?? 'NULL')}
                    </td>
                  ))
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Database Explorer & Diagnostics</h1>
          <p className="mt-1 text-sm text-gray-500">
            Execute secure, read-only diagnostic queries against configured MCP database targets.
          </p>
        </div>
      </div>

      <div className="grid lg:grid-cols-4 gap-6">
        <div className="lg:col-span-1 space-y-4">
          <div className="card">
            <label className="block text-sm font-medium text-gray-700 mb-1">Target Server</label>
            <div className="relative">
              <Database className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <select
                value={selectedServer}
                onChange={(e) => setSelectedServer(e.target.value)}
                className="pl-9 w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 sm:text-sm"
              >
                {servers.map(s => (
                  <option key={s.id} value={s.id}>{s.name} ({s.host || 'Unknown Host'})</option>
                ))}
              </select>
            </div>
          </div>
          
          <div className="card">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Diagnostic Templates</h3>
            <ul className="space-y-2 text-sm">
              <li>
                <button 
                  onClick={() => setQuery("SELECT tablespace_name, sum(bytes)/1024/1024/1024 as GB FROM dba_data_files GROUP BY tablespace_name;")} 
                  className="text-brand-600 hover:text-brand-800 text-left w-full hover:underline"
                >
                  Tablespace Usage (GB)
                </button>
              </li>
              <li>
                <button 
                  onClick={() => setQuery("SELECT status, count(*) FROM v$session GROUP BY status;")} 
                  className="text-brand-600 hover:text-brand-800 text-left w-full hover:underline"
                >
                  Active Sessions by Status
                </button>
              </li>
              <li>
                <button 
                  onClick={() => setQuery("SELECT * FROM v$waitstat ORDER BY count DESC FETCH FIRST 10 ROWS ONLY;")} 
                  className="text-brand-600 hover:text-brand-800 text-left w-full hover:underline"
                >
                  Top 10 Wait Stats
                </button>
              </li>
            </ul>
          </div>
        </div>

        <div className="lg:col-span-3 space-y-4">
          <div className="card flex flex-col h-64">
            <div className="flex justify-between items-center mb-2">
              <label className="block text-sm font-medium text-gray-700">SQL Query (Read-Only)</label>
              <button 
                onClick={handleExecute}
                disabled={loading || !selectedServer || !query.trim()}
                className="btn-primary py-1.5 flex items-center gap-2 text-sm disabled:opacity-50"
              >
                {loading ? <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" /> : <Play className="h-4 w-4" />}
                Execute
              </button>
            </div>
            <textarea
              className="flex-1 w-full rounded-md border-gray-300 shadow-sm focus:border-brand-500 focus:ring-brand-500 font-mono text-sm resize-none"
              placeholder="SELECT * FROM v$session WHERE status = 'ACTIVE'..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <div className="card min-h-64">
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-semibold text-gray-800">Results</h3>
              {execTime !== null && (
                <div className="flex items-center gap-1 text-xs text-gray-500">
                  <Clock className="h-3 w-3" />
                  <span>Execution time: {execTime.toFixed(1)} ms</span>
                </div>
              )}
            </div>
            
            {error ? (
              <div className="bg-red-50 text-red-700 p-4 rounded-md flex items-start gap-3">
                <AlertCircle className="h-5 w-5 mt-0.5 flex-shrink-0" />
                <div className="text-sm font-medium whitespace-pre-wrap">{error}</div>
              </div>
            ) : (
              renderTable()
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
