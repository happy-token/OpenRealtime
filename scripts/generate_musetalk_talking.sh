#!/usr/bin/env bash
# Runs on the configured GPU host. Inputs and results stay in the unique job directory.
set -euo pipefail
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
job_dir=$1
runtime_dir=$2
python_bin=$3
exec 9>"$runtime_dir/.openrealtime-talking.lock"
flock -w 1800 9
cd "$runtime_dir"
duration=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$job_dir/source.mp4")
ffmpeg -nostdin -v error -y -i "$job_dir/source.mp4" -an -vf fps=25 -c:v libx264 -crf 18 "$job_dir/idle.mp4"
ffmpeg -nostdin -v error -y -stream_loop -1 -i "$job_dir/reference.wav" -t "$duration" -ar 16000 -ac 1 "$job_dir/audio.wav"
"$python_bin" - "$job_dir" <<'PY'
import json
import pathlib
import sys
folder = pathlib.Path(sys.argv[1])
(folder / 'inference.json').write_text(json.dumps({'talking': {
    'video_path': str(folder / 'idle.mp4'),
    'audio_path': str(folder / 'audio.wav'),
    'result_name': 'talking.mp4',
}}))
PY
"$python_bin" -u -m scripts.inference --inference_config "$job_dir/inference.json" --result_dir "$job_dir/results" --unet_model_path models/musetalkV15/unet.pth --unet_config models/musetalkV15/musetalk.json --version v15 --batch_size 8 --use_float16
# The upstream script catches inference errors; require an actual, decodable result.
test -s "$job_dir/results/v15/talking.mp4"
ffmpeg -nostdin -v error -y -i "$job_dir/results/v15/talking.mp4" -an -vf 'tpad=stop_mode=clone:stop_duration=1' -t "$duration" -c:v libx264 -crf 18 -movflags +faststart "$job_dir/output.mp4"
ffmpeg -nostdin -v error -i "$job_dir/output.mp4" -f null -
