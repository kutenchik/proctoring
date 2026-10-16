/** Playback-only gain; never changes the evidence file or playback rate. */
export function gainChain(context: BaseAudioContext, source: AudioNode) {
  const gain=context.createGain(), limiter=context.createDynamicsCompressor();
  limiter.threshold.value=-6; limiter.knee.value=0; limiter.ratio.value=20;
  limiter.attack.value=.003; limiter.release.value=.15;
  source.connect(gain); gain.connect(limiter); limiter.connect(context.destination);
  return {set(value:number) {gain.gain.value=Math.max(1,Math.min(4,value));},
    close() {source.disconnect();gain.disconnect();limiter.disconnect();}};
}
