# Wav2Lip architecture provenance

The convolution blocks and Wav2Lip network definitions are adapted from the
Wav2Lip architecture distributed in lipku/LiveTalking, commit
36837f90f8db3f59e1d7fcdd111a7db3842515d0, avatars/wav2lip/models.
Original Wav2Lip: https://github.com/Rudrabha/Wav2Lip (ACM Multimedia 2020).
The 256 architecture is distributed by https://github.com/lipku/LiveTalking.
Only inference network definitions are retained; training discriminators are omitted.
Wav2Lip code/checkpoints retain their upstream non-commercial research/personal
usage restrictions. They are not relicensed by OpenRealtime's Apache license.
No LiveTalking application, avatar service, or transport is executed here.
