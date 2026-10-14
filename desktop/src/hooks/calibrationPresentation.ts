import { useEffect, useRef, useState } from 'react';
import type { CalibrationState, DisplayGeometry } from '../../shared/contracts';
import { command } from './backend';

let cueAudio: AudioContext | null = null;
let latestCue: { attempt: string; sequence: number } | null = null;
export function prepareCalibrationCues() {
  try { cueAudio ??= new AudioContext(); void cueAudio.resume(); } catch { /* Visual backend phase remains available. */ }
}
export function useCalibrationCue(calibration?: CalibrationState) {
  useEffect(() => {
    if (!calibration) return;
    const next = { attempt: calibration.attempt_id, sequence: calibration.cue_sequence };
    const previous = latestCue; latestCue = next;
    if (!previous || previous.attempt !== next.attempt || next.sequence <= previous.sequence) return;
    if (!cueAudio || cueAudio.state !== 'running' || !calibration.cue) return;
    const oscillator = cueAudio.createOscillator(); const gain = cueAudio.createGain();
    oscillator.frequency.value = calibration.cue === 'complete' ? 880 : 660;
    gain.gain.setValueAtTime(.08, cueAudio.currentTime);
    gain.gain.exponentialRampToValueAtTime(.001, cueAudio.currentTime + .12);
    oscillator.connect(gain); gain.connect(cueAudio.destination);
    oscillator.start(); oscillator.stop(cueAudio.currentTime + .13);
    oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
  }, [calibration?.attempt_id, calibration?.cue_sequence, calibration?.cue]);
}
export function useCalibrationPresentation(calibration: CalibrationState) {
  const [geometry, setGeometry] = useState<DisplayGeometry | null>(null);
  const [geometryError, setGeometryError] = useState(false);
  const acknowledged = useRef(new Set<string>());
  useEffect(() => {
    const api = window.proctoring; if (!api || api.mode !== 'live') return;
    let cancelled = false; let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try { const next = await api.geometry(); if (!cancelled) { setGeometry(old => old?.geometry_id === next.geometry_id ? old : next); setGeometryError(false); } }
      catch { if (!cancelled) { setGeometry(null); setGeometryError(true); } }
      finally { pending = false; }
    };
    void refresh(); const timer = window.setInterval(() => void refresh(), 300);
    window.addEventListener('resize', refresh);
    return () => { cancelled = true; clearInterval(timer); window.removeEventListener('resize', refresh); };
  }, []);
  useEffect(() => {
    const token = calibration.presentation_token;
    if (calibration.phase !== 'awaiting_presentation' || !token || !geometry || geometryError || (calibration.target === 'CENTER' && !geometry.center_visible)) return;
    const key = `${calibration.attempt_id}:${token}:${geometry.geometry_id}`;
    if (acknowledged.current.has(key)) return;
    let second = 0;
    const first = requestAnimationFrame(() => { second = requestAnimationFrame(() => {
      acknowledged.current.add(key);
      void command('calibration.presented', { token, target: calibration.target, geometry_id: geometry.geometry_id }).then(ok => { if (!ok) acknowledged.current.delete(key); });
    }); });
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); };
  }, [calibration.phase, calibration.presentation_token, calibration.attempt_id, calibration.target, geometry, geometryError]);
  return { geometry, geometryError };
}
