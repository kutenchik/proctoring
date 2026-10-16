export interface Teacher { id: string; name: string; email: string }
export interface Auth { teacher: Teacher; csrf_token: string }
export interface Option { id: string; text: string }
export interface Question { id: string; type: 'single_choice' | 'multiple_choice'; prompt: string; options: Option[]; correct_option_ids: string[] }
export interface QuestionSet { title: string; questions: Question[]; id?: string; created_at?: string }
export interface LibrarySummary { id: string; title: string; question_count: number; created_at: string }
export interface Exam {
  id: string; title: string; code: string; exam_type: 'native' | 'external';
  admission_start: string; admission_close: string; duration_seconds: number; timezone: string;
  policy: ExamPolicy; external_url?: string; library_id?: string;
  phase: 'active' | 'upcoming' | 'completed'; attempt_count: number; participant_count: number;
  quiz?: QuestionSet | null;
}
export interface ExamPolicy {
  shuffle_questions: boolean; shuffle_options: boolean; audio_monitoring: boolean; save_snapshots: boolean;
  protection_mode: 'protected' | 'unprotected';
  monitoring_policy?: import('./Configuration').Policy;
}
export type ExamInput = Omit<Exam, 'id' | 'code' | 'phase' | 'attempt_count' | 'participant_count' | 'quiz' | 'policy'> & ExamPolicy;
export interface Attempt {
  id: string; full_name: string; group: string; student_id: string;
  status: string; admitted_at: string; preparation_deadline: string;
  started_at?: string | null; finished_at?: string | null;
  score?: number | null; total?: number | null; end_reason?: string | null;
  repeat_authorized?: boolean;
}

export class ApiError extends Error {
  constructor(public code: string, public status: number, public serverMessage = '', public fields: string[] = []) {
    super(code); this.name = 'ApiError';
  }
}

/** Same-origin requests only. The HttpOnly session cookie never enters JS/storage. */
export class TeacherApi {
  private csrf = '';
  setAuth(auth: Auth | null) { this.csrf = auth?.csrf_token ?? ''; }
  async request<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
    if (!path.startsWith('/') || path.startsWith('//')) throw new Error('invalid_api_path');
    const headers: Record<string, string> = {};
    const multipart = data instanceof FormData;
    if (data !== undefined && !multipart) headers['Content-Type'] = 'application/json';
    if (method !== 'GET' && this.csrf) headers['X-CSRF-Token'] = this.csrf;
    let response: Response;
    try {
      response = await fetch(`/api/v1${path}`, {
        method, headers, credentials: 'same-origin', cache: 'no-store',
        body: data === undefined ? undefined : multipart ? data : JSON.stringify(data),
        signal: AbortSignal.timeout(20_000),
      });
    } catch { throw new ApiError('network_unavailable', 0); }
    const json = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = json?.detail;
      const fields = Array.isArray(detail) ? detail.map((e: {loc?: unknown[]}) => e.loc?.filter(x => x !== 'body').join('.') ?? '') : [];
      throw new ApiError(detail?.code ?? (response.status === 401 ? 'authentication_required' : 'request_failed'), response.status, typeof detail?.message === 'string' ? detail.message : '', fields);
    }
    return json as T;
  }
  async me() { const auth = await this.request<Auth>('/auth/me'); this.setAuth(auth); return auth; }
  async login(email: string, password: string) {
    const auth = await this.request<Auth>('/auth/login', 'POST', {email, password}); this.setAuth(auth); return auth;
  }
  async logout() { await this.request('/auth/logout', 'POST'); this.setAuth(null); }
  preview(file: File) { const data = new FormData(); data.append('file', file); return this.request<QuestionSet>('/libraries/preview', 'POST', data); }
}
export const api = new TeacherApi();
