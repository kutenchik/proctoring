import { Camera, CameraOff, ScanFace } from 'lucide-react';
import type { BackendState } from '../../shared/contracts';
import { usePreview } from '../hooks/backend';
import { useT } from '../locales';
type Overlay = { kind: 'box' | 'ellipse'; label?: string; x1: number; y1: number; x2: number; y2: number; ready?: boolean };
function validOverlay(value: unknown): value is Overlay {
  if (!value || typeof value !== 'object') return false;
  const b = value as Record<string, unknown>;
  return (b.kind === 'box' || b.kind === 'ellipse') && ['x1','y1','x2','y2'].every(key => typeof b[key] === 'number' && Number.isFinite(b[key]) && b[key] >= 0 && b[key] <= 1) && Number(b.x1) < Number(b.x2) && Number(b.y1) < Number(b.y2);
}
export function CameraPreview({ camera, connected = true, fixture = false, guide = false, guideBounds, aligned = true, compact = false }: { camera?: BackendState['camera']; connected?: boolean; fixture?: boolean; guide?: boolean; guideBounds?: number[]; aligned?: boolean; compact?: boolean }) {
  const t = useT();
  const frame = usePreview(!fixture && connected && camera?.state === 'live', camera?.selected_key);
  const live = !!frame && connected && camera?.state === 'live';
  const unavailable = !connected || camera?.state === 'unavailable' || camera?.state === 'stale';
  const overlays = frame?.overlays.filter(validOverlay) ?? [];
  return <div className={`camera-preview ${compact ? 'camera-compact' : ''} ${fixture ? 'camera-fixture' : ''}`}>
    {live && frame ? <img className="camera-image" alt={t('live')} src={`data:${frame.mime};base64,${frame.jpeg_base64}`} width={frame.width} height={frame.height} /> : fixture ? <div className="preview-illustration" aria-hidden="true"><div className="illustration-shoulders"/><div className="illustration-head"><div className="illustration-eyes"><i/><i/></div><div className="illustration-nose"/><div className="illustration-mouth"/></div></div> : <div className="camera-empty">{unavailable ? <CameraOff aria-hidden="true" size={30} strokeWidth={1.5} /> : <Camera aria-hidden="true" size={30} strokeWidth={1.5} />}<strong>{unavailable ? t('stale') : camera?.state === 'opening' ? t('opening') : t('cameraOff')}</strong><span>{unavailable ? camera?.error : t('cameraOffHint')}</span></div>}
    {guide && fixture && <div className={`face-guide ${aligned ? 'guide-ready' : ''}`} aria-hidden="true"/>}
    {live && frame && <svg className="source-overlays" viewBox={`0 0 ${frame.source_width} ${frame.source_height}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      {overlays.map((box, i) => box.kind === 'ellipse' ? <ellipse key={i} cx={(box.x1 + box.x2) / 2 * frame.source_width} cy={(box.y1 + box.y2) / 2 * frame.source_height} rx={(box.x2 - box.x1) / 2 * frame.source_width} ry={(box.y2 - box.y1) / 2 * frame.source_height} fill="none" stroke={box.ready ? 'hsl(110 38% 66%)' : 'hsl(28 76% 58%)'} strokeWidth={2} vectorEffect="non-scaling-stroke"/> : <rect key={i} x={box.x1 * frame.source_width} y={box.y1 * frame.source_height} width={(box.x2 - box.x1) * frame.source_width} height={(box.y2 - box.y1) * frame.source_height} fill="none" stroke={box.label === 'phone' ? 'hsl(28 76% 58%)' : 'hsl(110 38% 66%)'} strokeWidth={box.label === 'face' ? 1 : 2} vectorEffect="non-scaling-stroke"/>) }
      {guide && !overlays.some(box => box.kind === 'ellipse') && guideBounds?.length === 4 && <ellipse cx={(guideBounds[0] + guideBounds[2]) / 2 * frame.source_width} cy={(guideBounds[1] + guideBounds[3]) / 2 * frame.source_height} rx={(guideBounds[2] - guideBounds[0]) / 2 * frame.source_width} ry={(guideBounds[3] - guideBounds[1]) / 2 * frame.source_height} fill="none" stroke={aligned ? 'hsl(110 38% 66%)' : 'hsl(28 76% 58%)'} strokeWidth={2} vectorEffect="non-scaling-stroke"/>}
    </svg>}
    {(live || fixture) && <div className="preview-top"><span className="preview-tag"><span className="status-dot"/>{fixture ? t('fixture') : t('live')}</span>{guide && <span className="preview-tag"><ScanFace aria-hidden="true" size={14}/>{aligned ? t('faceAligned') : t('holdStill')}</span>}</div>}
    {(live || fixture) && <div className="preview-bottom">{fixture ? t('sampleCamera') : `${t('source')} ${frame?.source_width} × ${frame?.source_height}`}</div>}
  </div>;
}
