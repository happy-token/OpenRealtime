"""Server-owned registry mapping stable plugin identities to bindings."""

from __future__ import annotations

from dataclasses import dataclass

from server.realtime.profile.models import PluginManifest


class PluginNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class RegisteredPlugin:
    manifest: PluginManifest
    binding: object


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[tuple[str, str], RegisteredPlugin] = {}

    def register(self, manifest: PluginManifest, *, binding: object) -> None:
        key = (manifest.plugin_id, manifest.plugin_version)
        if key in self._plugins:
            raise ValueError(f"plugin {manifest.plugin_id}@{manifest.plugin_version} is registered")
        self._plugins[key] = RegisteredPlugin(manifest=manifest, binding=binding)

    def resolve(self, plugin_id: str, plugin_version: str) -> RegisteredPlugin:
        try:
            return self._plugins[(plugin_id, plugin_version)]
        except KeyError as error:
            raise PluginNotFound(
                f"plugin {plugin_id}@{plugin_version} is not registered"
            ) from error
