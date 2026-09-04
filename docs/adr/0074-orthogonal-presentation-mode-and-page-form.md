# Keep presentation mode and page form orthogonal

OpenRealtime models `对话模式` versus `数字人模式` as Presentation Mode, and `全屏` versus `Sidecar` versus `内容` as an independently selected Page Form. This replaces the previous top-level `对话 / 聊天 / 数字人` choice: conversation history belongs to page composition rather than visual embodiment, so a single six-value mode enum would duplicate semantics and make switching layout more likely to disturb one Voice Session's presentation state.
