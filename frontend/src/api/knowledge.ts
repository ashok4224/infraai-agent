import api from './client';

// ── Types ──────────────────────────────────────────────────────────────

export interface KnowledgeSource {
  id: string;
  name: string;
  description: string | null;
  source_type: string;
  connection_config: Record<string, any>;
  filter_config: Record<string, any>;
  sync_interval_hours: number;
  last_synced_at: string | null;
  sync_status: string;
  sync_error: string | null;
  is_active: boolean;
  doc_count: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeSearchResult {
  chunk_content: string;
  score: number;
  document_title: string;
  source_name: string;
  source_type: string;
  file_path: string | null;
  metadata: Record<string, any>;
}

export interface RAGSettings {
  rag_enabled: boolean;
  rag_embedding_model: string;
  rag_chunk_size: number;
  rag_chunk_overlap: number;
  rag_top_k: number;
  rag_score_threshold: number;
}

export interface SyncPreview {
  estimated_documents: number;
  estimated_chunks: number;
  estimated_tokens: number;
  estimated_cost_usd: number;
  source_type: string;
  filters_applied: Record<string, any>;
}

// ── API calls ──────────────────────────────────────────────────────────

export const knowledgeApi = {
  getSettings: () => api.get<RAGSettings>('/knowledge/settings'),

  listSources: () => api.get<KnowledgeSource[]>('/knowledge/sources'),

  getSource: (id: string) => api.get<KnowledgeSource>(`/knowledge/sources/${id}`),

  createSource: (data: Partial<KnowledgeSource>) =>
    api.post<KnowledgeSource>('/knowledge/sources', data),

  updateSource: (id: string, data: Partial<KnowledgeSource>) =>
    api.put<KnowledgeSource>(`/knowledge/sources/${id}`, data),

  deleteSource: (id: string) => api.delete(`/knowledge/sources/${id}`),

  triggerSync: (id: string) => api.post(`/knowledge/sources/${id}/sync`),

  getSyncStatus: (id: string) => api.get(`/knowledge/sources/${id}/sync-status`),

  testConnection: (id: string) => api.post(`/knowledge/sources/${id}/test-connection`),

  previewSync: (id: string) => api.post<SyncPreview>(`/knowledge/sources/${id}/preview`),

  search: (query: string, topK = 5) =>
    api.post<{ results: KnowledgeSearchResult[]; query: string; total: number }>(
      '/knowledge/search',
      { query, top_k: topK }
    ),

  uploadFile: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/knowledge/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
};
