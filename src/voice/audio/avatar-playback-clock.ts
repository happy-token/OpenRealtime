/** Media time, rather than elapsed wall time, stops advancing during playback stalls. */
export interface AvatarMediaClock {
  volume: number;
  currentTime?: number;
  paused?: boolean;
  readyState?: number;
}

export interface AvatarPlaybackPosition {
  generation: number;
  speechId: string;
  playedAudioEndUs: number;
}

export class AvatarPlaybackClock {
  private anchor: number | null = null;
  private durationUs = 0;
  private positionUs = 0;

  constructor(readonly generation: number, readonly speechId: string) {}

  append(base64: string, sampleRateHz: number): void {
    const padding = base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0;
    const bytes = Math.max(0, Math.floor(base64.length * 3 / 4) - padding);
    this.durationUs += Math.floor(bytes / 2) / sampleRateHz * 1_000_000;
  }

  start(media: AvatarMediaClock | null): void {
    if (this.anchor === null && media && Number.isFinite(media.currentTime)) {
      this.anchor = media.currentTime!;
    }
  }

  read(media: AvatarMediaClock | null): AvatarPlaybackPosition | null {
    if (this.anchor === null || !media || !Number.isFinite(media.currentTime)) return null;
    if (!media.paused && (media.readyState === undefined || media.readyState >= 2)) {
      this.positionUs = Math.max(this.positionUs, Math.min(
        this.durationUs, Math.max(0, media.currentTime! - this.anchor) * 1_000_000,
      ));
    }
    return { generation: this.generation, speechId: this.speechId, playedAudioEndUs: Math.round(this.positionUs) };
  }
}
