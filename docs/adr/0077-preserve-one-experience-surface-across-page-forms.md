# Preserve one experience surface across page forms

Fullscreen, Sidecar, and Content Form recompose one mounted Experience Surface plus one conversation/composer instance instead of mounting a separate tree per layout. Recreating the current digital-human stage would tear down its Avatar Renderer and audio binding, while duplicated transcript and composer trees would split scroll, streaming-item, and draft state; layout containers may animate, but Page Form changes cannot restart session-bound presentation services.
