# Bind presentation mode for the lifetime of a Voice Session

Presentation Mode is chosen before Voice Session startup and remains immutable until that Session ends. Digital-human presentation requires starting and binding mode-specific Avatar Renderer and model services, while Orb presentation does not; treating them as a live visual toggle would hide a service-lifecycle transition and risk conflicting playback ownership. Page Form remains freely switchable because it only recomposes the already bound Experience Surface and conversation content.
