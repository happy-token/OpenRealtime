# Digital-human media

The tracked built-in collection contains three avatars: 萨曼莎, 清照, and 若水.
Their packaged catalog is `src/data/builtin-avatar-catalog.json`; the source
images, motion bases, and talking variants referenced by that catalog are the
explicitly unignored files in this directory. A fresh local catalog loads
these records when `.openrealtime/avatar-catalog/catalog.json` is absent.
The built-in reference audio for offline lip sync is packaged separately at
`src/data/builtin-talking-reference.wav`.

Other research portraits and media in this directory remain local and are
excluded from the source package. Some older locally saved actions use the
separate avatar-asset control service and are not part of the portable built-in
catalog. Media redistribution rights should be checked before publishing the
source package or deploying it publicly.
