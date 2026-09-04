import hashlib
from pathlib import Path

import pytest

from scripts.setup_wav2lip_runtime import (
    WAV2LIP_COMMIT,
    _install_verified_weight,
    apply_wav2lip_compatibility_patches,
    build_wav2lip_setup_plan,
)


def test_setup_plan_pins_official_source_and_smallest_inference_weight_set() -> None:
    plan = build_wav2lip_setup_plan(Path("models/wav2lip"))

    assert plan.repository_url == "https://github.com/Rudrabha/Wav2Lip.git"
    assert plan.commit == "bac9a81e63ecc153202353372e5724b83d9e6322"
    assert plan.commit == WAV2LIP_COMMIT
    assert plan.python_version == "3.10.20"
    assert plan.minimum_free_bytes == 6 * 1024**3
    assert plan.expected_weight_bytes == 525_651_076
    assert plan.weight_files == (
        "checkpoints/wav2lip.pth",
        "face_detection/detection/sfd/s3fd.pth",
    )
    assert "wav2lip_gan.pth" not in plan.weight_files
    assert plan.lock_file.name == "wav2lip-macos-arm64-py310.txt"
    assert "torch==2.13.0" in plan.lock_file.read_text(encoding="utf-8")


def test_compatibility_patch_modernizes_audio_mps_and_ffmpeg_calls(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    (repository / "face_detection/detection/sfd").mkdir(parents=True)
    (repository / "face_detection/detection").mkdir(parents=True, exist_ok=True)
    (repository / "audio.py").write_text(
        """
return librosa.core.load(path, sr=sr)[0]
    librosa.output.write_wav(path, wav, sr=sr)
return librosa.filters.mel(hp.sample_rate, hp.n_fft, n_mels=hp.num_mels,
""".strip(),
        encoding="utf-8",
    )
    (repository / "inference.py").write_text(
        """
device = 'cuda' if torch.cuda.is_available() else 'cpu'
checkpoint = torch.load(checkpoint_path)
checkpoint = torch.load(checkpoint_path,
                                map_location=lambda storage, loc: storage)
if os.path.isfile(args.face) and args.face.split('.')[1] in ['jpg', 'png', 'jpeg']:
elif args.face.split('.')[1] in ['jpg', 'png', 'jpeg']:
frame = cv2.rotate(frame, cv2.cv2.ROTATE_90_CLOCKWISE)
command = 'ffmpeg -y -i {} -i {} -strict -2 -q:v 1 {}'.format(args.audio, 'temp/result.avi', args.outfile)
	subprocess.call(command, shell=platform.system() != 'Windows')
""".strip(),
        encoding="utf-8",
    )
    (repository / "face_detection/utils.py").write_text(
        "newDim = np.array([1, 2], dtype=np.int)", encoding="utf-8"
    )
    (repository / "face_detection/detection/core.py").write_text(
        "if 'cpu' not in device and 'cuda' not in device:", encoding="utf-8"
    )
    (repository / "face_detection/detection/sfd/sfd_detector.py").write_text(
        "model_weights = torch.load(path_to_detector)", encoding="utf-8"
    )

    apply_wav2lip_compatibility_patches(repository)
    audio = (repository / "audio.py").read_text(encoding="utf-8")
    inference = (repository / "inference.py").read_text(encoding="utf-8")
    detector_core = (repository / "face_detection/detection/core.py").read_text(encoding="utf-8")
    assert "librosa.load(path, sr=sr)" in audio
    assert "librosa.filters.mel(sr=hp.sample_rate, n_fft=hp.n_fft" in audio
    assert "sf.write(path, wav, sr)" in audio
    assert "WAV2LIP_DEVICE_OVERRIDE" in inference
    assert "weights_only=True" in inference
    assert "weights_only=False" not in inference
    assert "os.path.splitext(args.face)" in inference
    assert "subprocess.run([" in inference
    assert "check=True" in inference
    assert "'mps' not in device" in detector_core

    # A repair install must be safe to repeat.
    apply_wav2lip_compatibility_patches(repository)


def test_weight_install_rejects_a_symlink_destination(tmp_path: Path) -> None:
    weight_root = tmp_path / "repository"
    weight_root.mkdir()
    downloaded = tmp_path / "downloaded.pth"
    downloaded.write_bytes(b"verified")
    outside = tmp_path / "outside.pth"
    outside.write_bytes(b"keep")
    destination = weight_root / "model.pth"
    destination.symlink_to(outside)

    with pytest.raises(RuntimeError, match="symbolic link"):
        _install_verified_weight(
            downloaded,
            destination,
            root=weight_root,
            expected_sha256=hashlib.sha256(b"verified").hexdigest(),
        )

    assert outside.read_bytes() == b"keep"
