import type { Attempt, Exam } from './api';

export const reviewDecisions = ['not_reviewed', 'confirmed', 'false_positive', 'insufficient_evidence'] as const;
export type ReviewDecision = typeof reviewDecisions[number];
export const conclusionDecisions = ['none_confirmed', 'violation_confirmed', 'insufficient_evidence'] as const;
export type ConclusionDecision = typeof conclusionDecisions[number];
export interface EventDecision {
  version: number; decision: ReviewDecision; comment: string;
  teacher_id?: string; teacher_name?: string; created_at?: string;
}
export interface ReviewChange {
  version?: number; teacher_id?: string; teacher_name?: string; author_name?: string; created_at?: string; updated_at?: string;
  old_decision?: string; new_decision?: string; old_comment?: string; new_comment?: string;
  decision?: string; comment?: string; category?: string; description?: string; cancelled?: boolean;
}
export interface EvidenceFile {id: string; kind: string; filename?: string; relative_path?: string; size?: number; sha256?: string; received_bytes?: number; complete?: boolean; requirement?: string; status?: string; error?: string;}
export interface ReviewEvent {
  event_id: string; event_type: string; timestamp: string; duration_seconds: number;
  category: 'behavioral' | 'technical'; files: EvidenceFile[];
  review: EventDecision | null; history: ReviewChange[];
}
export interface EventGroup {id: string; event_type: string; event_ids: string[]; category: 'behavioral' | 'technical';}
export interface ManualObservation {
  id: string; version: number; category: string; description: string; cancelled: boolean;
  phase: 'during_exam' | 'later_review'; author_id: string; author_name: string;
  created_at: string; updated_at: string; history: ReviewChange[];
}
export interface Conclusion {
  id: string; version: number; decision: ConclusionDecision; comment: string;
  unreviewed_count: number; teacher_id: string; teacher_name: string; created_at: string;
  needs_reconsideration: boolean; report_status: string; report_url?: string;
}
export interface SyncState {
  status?: string; lifecycle?: string; receipt_complete?: boolean; receipt?: {verified_at?: string; complete?: boolean; manifest_sha256?: string} | null;
  files?: EvidenceFile[]; missing?: string[]; deleted_at?: string | null; retention_until?: string | null;
  manifest?: {items: Array<EvidenceFile & {required: boolean; status: string}>} | null;
  recovery?: {interruption_id?: string; grant_id?: string; state?: string; checkpoint?: unknown};
  server_result?: Record<string,unknown> | null; client_result?: Record<string,unknown> | null;
  timing?: {started_at?: string|null; ended_at?: string|null; elapsed_seconds?: number|null; remaining_seconds?: number|null};
  [key: string]: unknown;
}
export interface ReviewAttempt extends Attempt {
  exam_id: string; sequence: number; elapsed_seconds?: number; remaining_seconds?: number;
  lifecycle?: string; sync_state?: string; verified_score?: number | null; verified_total?: number | null;
  result_integrity?: string | null; result_source?: string;
}
export interface ReviewDocument {
  attempt: ReviewAttempt; exam: Exam; sync: SyncState;
  events: ReviewEvent[]; groups: EventGroup[]; manual_observations: ManualObservation[];
  conclusion: Conclusion | null; conclusion_history: Conclusion[];
  unreviewed_count: number; can_finalize: boolean;
}

export function decisionFor(event: ReviewEvent): EventDecision {
  return event.review ?? {version: 0, decision: 'not_reviewed', comment: ''};
}
export function reviewPayload(events: ReviewEvent[], decision: ReviewDecision, comment: string) {
  return {items: events.map(event => ({event_id: event.event_id, expected_version: decisionFor(event).version, decision, comment: comment.trim()}))};
}
export function eventsInGroup(document: Pick<ReviewDocument,'events'>, group: EventGroup): ReviewEvent[] {
  const ids = new Set(group.event_ids); return document.events.filter(event => ids.has(event.event_id));
}
export function mayFinalize(document: Pick<ReviewDocument,'can_finalize'|'unreviewed_count'>, acknowledged: boolean) {
  return document.can_finalize && (document.unreviewed_count === 0 || acknowledged);
}
export function evidenceUrl(attemptId: string, fileId: string) {
  return `/api/v1/attempts/${encodeURIComponent(attemptId)}/evidence/${encodeURIComponent(fileId)}`;
}
export function reviewedPdfUrl(attemptId: string, version: number) {
  return `/api/v1/attempts/${encodeURIComponent(attemptId)}/reports/reviewed/${version}`;
}
export function safeDuration(value: unknown) {return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value.toFixed(2) : '—';}
