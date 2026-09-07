"""Offline export using the exact inference/composition functions of the realtime service.

For acceptance, use scripts/record_avatar_realtime.py to capture the actual
WebRTC output instead. --repo is an asset/checkpoint location, never an app.
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.avatar_compositing import CompositionConfig, MaskMode
from server.avatar_compositing.runtime import FPS, AvatarFrames, AvatarRenderer, mel_spectrogram
from server.avatar_compositing.service import decode_wav


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--avatar', required=True)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--blend', type=float, default=os.environ.get("OPENREALTIME_WAV2LIP_BLEND", "0.5"))
    parser.add_argument('--mask-mode', choices=('mouth', 'full'), default='mouth')
    parser.add_argument('--feather', type=float, default=0.35)
    parser.add_argument('--model-size', type=int, choices=(96, 256), default=256)
    parser.add_argument('--inference-stride', type=int, choices=(1, 2), default=2)
    parser.add_argument('--batch-size', type=int, default=4)
    parser.add_argument('--fps', type=int, choices=(25,), default=FPS)
    parser.add_argument('--speech-mode', choices=('wav2lip',), default='wav2lip')
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 16 or args.batch_size % args.inference_stride:
        parser.error('batch-size must be divisible by stride and between 1 and 16')
    if not 0 <= args.blend <= 1:
        parser.error('blend must be between 0 and 1')
    pcm = decode_wav(args.audio.read_bytes())
    mel = mel_spectrogram(pcm.astype(np.float32) / 32768)
    avatar = AvatarFrames.load(args.repo / 'data/avatars', args.avatar, args.model_size)
    renderer = AvatarRenderer(args.repo / 'models' / ('wav2lip256.pth' if args.model_size == 256 else 'wav2lip.pth'),
                              args.model_size, stride=args.inference_stride,
                              config=CompositionConfig(wav2lip_blend=args.blend,
                                                       mask_mode=MaskMode(args.mask_mode), mask_feather=args.feather))
    count = math.ceil(len(pcm) / 640)
    height, width = avatar.frame(0).shape[:2]
    carry = {}
    with tempfile.TemporaryDirectory(prefix='openrealtime-video-') as directory:
        silent = Path(directory) / 'silent.mp4'
        writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*'mp4v'), FPS, (width, height))
        if not writer.isOpened():
            raise RuntimeError('Could not create video writer')
        try:
            for start in range(0, count, args.batch_size):
                frames, _ = renderer.render_batch(avatar, mel, start, start, min(args.batch_size, count-start), carry)
                for frame in frames:
                    writer.write(frame)
        finally:
            writer.release()
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(silent), '-i', str(args.audio),
                        '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                        '-movflags', '+faststart', '-shortest', str(args.output)], check=True)
    print(f'Wrote {count} frames: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
