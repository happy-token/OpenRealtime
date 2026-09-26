#!/usr/bin/env bash
set -euo pipefail

job_dir=$1
runtime_dir=$2
python_bin=$3
exec 9>"$runtime_dir/.openrealtime-lipforcing.lock"
flock -w 3600 9
cd "$runtime_dir"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
export HF_HUB_OFFLINE=1
export WANDB_MODE=disabled
export WANDB_DISABLED=true
export LIPFORCING_DISABLE_FLEX_ATTENTION=1

duration=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$job_dir/source.mp4")
ffmpeg -nostdin -v error -y -i "$job_dir/source.mp4" -an -vf fps=25 -c:v libx264 -crf 18 "$job_dir/idle.mp4"
ffmpeg -nostdin -v error -y -stream_loop -1 -i "$job_dir/reference.wav" -t "$duration" -ar 16000 -ac 1 "$job_dir/audio.wav"

entrypoint="${LIPFORCING_REMOTE_ENTRYPOINT:-infer_lowmem.py}"
test -f "$entrypoint"
text_args=(--text_embeds_path "${LIPFORCING_TEXT_EMBEDS_PATH:-weights/person-talking-text-emb.pt}")

"$python_bin" -u "$entrypoint" \
  --ckpt_path "${LIPFORCING_CKPT_PATH:-weights/lipforcing_14b.pth}" \
  --vae_path "${LIPFORCING_VAE_PATH:-weights/Wan2.1-T2V-14B/Wan2.1_VAE.pth}" \
  --wav2vec_path "${LIPFORCING_WAV2VEC_PATH:-weights/wav2vec2-base-960h}" \
  --mask_path "${LIPFORCING_MASK_PATH:-weights/mask.png}" \
  --streaming_decoder wan_vae \
  --dtype bf16 \
  --seed 42 \
  --video_path "$job_dir/idle.mp4" \
  --audio_path "$job_dir/audio.wav" \
  --output_path "$job_dir/generated.mp4" \
  --face_cache_dir "$job_dir/face-cache" \
  "${text_args[@]}"

test -s "$job_dir/generated.mp4"
ffmpeg -nostdin -v error -y -i "$job_dir/generated.mp4" -an -vf 'tpad=stop_mode=clone:stop_duration=1' -t "$duration" -c:v libx264 -crf 18 -movflags +faststart "$job_dir/output.mp4"
ffmpeg -nostdin -v error -i "$job_dir/output.mp4" -f null -
