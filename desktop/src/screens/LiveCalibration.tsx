import { Check, CircleAlert, Eye, ScanFace } from 'lucide-react';
import type { BackendState, WorkflowState } from '../../shared/contracts';
import { CameraPreview } from '../components/CameraPreview';
import { Button, Badge } from '../components/ui';
import { command } from '../hooks/backend';
import { prepareCalibrationCues, useCalibrationPresentation } from '../hooks/calibrationPresentation';
import { useT } from '../locales';
import { useW } from '../locales/workflow';

export function LiveCalibration({ state, workflow, busy }: { state: BackendState; workflow: WorkflowState; busy: boolean }) {
  const t = useT(); const w = useW(); const c = workflow.calibration;
  const { geometry, geometryError } = useCalibrationPresentation(c);
  const collecting = ['awaiting_presentation', 'preparing', 'collecting'].includes(c.phase);
  const failed = c.phase === 'fit_failed' || c.phase === 'target_failed';
  const prompt = c.target === 'LEFT' ? t('leftTarget') : c.target === 'RIGHT' ? t('rightTarget') : c.target === 'DOWN' ? t('downTarget') : t('centerTarget');
  const noCenter = c.target === 'CENTER' && geometry && !geometry.center_visible;
  const alignmentMessages: Record<string, string> = {
    monitoring_unavailable: w('waitHealthyCamera'), no_frame: w('waitFreshFrame'), stale_frame: w('waitFreshFrame'), timestamp_regressed: w('waitFreshFrame'),
    source_dimensions_missing: w('waitSourceDimensions'), head_pose_unavailable: w('faceScreen'), head_not_frontal: w('faceScreen'),
    eyes_not_visible: t('eyesVisible'), eye_size_unavailable: t('eyesVisible'), eye_quality_low: t('eyesVisible'),
    no_face: w('centerFace'), face_not_contained: w('centerFace'), face_too_small: t('moveCloser'), hold_still: t('holdStill'),
    eye_measurements_disagree: w('eyesDisagree'), eye_measurements_invalid: w('eyesUnavailable'),
  };
  return <><div className="page-title"><div><p className="eyebrow">02 / {t('stepGaze')}</p><h1>{t('gazeTitle')}</h1><p>{t('gazeHelp')}</p></div></div>
    <div className="calibration-grid"><section className="panel"><CameraPreview camera={state.camera} guide guideBounds={c.alignment.guide} aligned={c.alignment.ready}/><div className="alignment-feedback"><ScanFace size={20} aria-hidden="true"/><strong>{c.alignment.ready ? t('faceAligned') : alignmentMessages[c.alignment.reason] ?? c.alignment.message}</strong><Badge tone={c.alignment.ready ? 'success' : 'warning'}>{w('alignment')}</Badge></div><progress value={c.alignment.progress} max={1} aria-label={w('alignment')}/><p className="quiet-note">{t('gazeHelp')}</p></section>
    <section className="panel target-panel"><div className="target-top"><Badge>{c.completed_targets.length + 1} / 4</Badge><span className="eyebrow">{t('calibration')}</span></div><div className="target-icon"><Eye size={32} aria-hidden="true"/></div><p className="target-name">{c.target}</p><h2>{prompt}</h2>
      <p role="status">{c.phase === 'preparing' ? `${w('preparing')} · ${Math.ceil(c.prepare_remaining)} ${w('seconds')}` : c.phase === 'collecting' ? t('collecting') : c.phase === 'awaiting_presentation' ? w('waitingTarget') : failed ? w('calibrationFailed') : w('calibrationIdle')}</p>
      <div className="sample-progress"><div><span>{w('accepted')}</span><b className="numeric">{c.accepted_samples} / {c.required_samples}</b></div><progress aria-label={t('samples')} value={c.accepted_samples} max={c.required_samples}/></div>
      {(failed || noCenter || geometryError) && <div className="notice notice-warning" role="status"><CircleAlert size={19} aria-hidden="true"/><div><strong>{noCenter ? w('physicalCenterUnavailable') : geometryError ? w('geometryChanged') : w('calibrationFailed')}</strong><p>{c.message}</p></div></div>}
      <div className="actions wrap live-calibration-actions"><Button disabled={busy || collecting || !c.alignment.ready || !!noCenter || !geometry || c.phase === 'fit_failed'} onClick={() => { prepareCalibrationCues(); void command(c.phase === 'target_failed' ? 'calibration.retry' : 'calibration.start', c.phase === 'target_failed' ? { scope: 'target' } : undefined); }}>{c.phase === 'target_failed' ? t('retry') : t('prepare')}</Button><Button variant="secondary" disabled={busy} onClick={() => void command('calibration.cancel')}>{w('cancelCalibration')}</Button>{failed && <Button variant="ghost" disabled={busy} onClick={() => void command('calibration.retry', { scope: 'baseline' })}>{w('resetBaseline')}</Button>}</div>
      <p className="quiet-note">{c.message}</p><div className="quality-checks">{c.completed_targets.map(target => <span key={target}><Check size={14} aria-hidden="true"/>{target}</span>)}</div>
    </section></div>
    <Button variant="ghost" disabled={busy} onClick={() => void command('setup.show')}>{w('backDevices')}</Button>
    <details className="panel diagnostics-panel"><summary>{t('diagnostics')}</summary><div className="diagnostics-content"><span>{w('attempt')}: {c.attempt_id}</span><span>{w('finalFit')}: {c.ready ? w('calibrationPassed') : w('waiting')}</span><span>{w('diagnosticConfig')}: {workflow.config_path}</span><pre className="technical">{JSON.stringify(c.diagnostics, null, 2)}</pre></div></details>
    {collecting && c.target === 'CENTER' && geometry?.center_visible && <div className="physical-target" style={{ left: geometry.center_client.x, top: geometry.center_client.y }} aria-label={t('centerTarget')}><span/></div>}
  </>;
}
