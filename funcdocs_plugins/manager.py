import importlib
import pkgutil
import re
from pathlib import Path

from funcdocs_plugins.api import FuncDocsPlugin


class PluginManager:
    PLUGIN_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]*\Z")

    def __init__(self):
        self.plugin_directory = Path(__file__).resolve().parent.parent / "plugins"
        self.plugins = []
        self.errors = []

    def discover(self):
        self.plugins = []
        self.errors = []
        plugin_ids = set()

        for module_info in sorted(
            pkgutil.iter_modules([str(self.plugin_directory)]),
            key=lambda item: item.name,
        ):
            module_name = module_info.name
            if module_name.startswith("_"):
                continue

            try:
                module = importlib.import_module(f"plugins.{module_name}")
                factory = getattr(module, "create_plugin", None)
                if not callable(factory):
                    raise TypeError("create_plugin() factory is required")

                plugin = factory()
                if not isinstance(plugin, FuncDocsPlugin):
                    raise TypeError("create_plugin() must return FuncDocsPlugin")
                if not self.PLUGIN_ID_PATTERN.fullmatch(plugin.plugin_id):
                    raise ValueError(
                        f"Invalid plugin_id: {plugin.plugin_id!r}"
                    )
                if plugin.plugin_id in plugin_ids:
                    raise ValueError(f"Duplicate plugin_id: {plugin.plugin_id}")
                if (
                    not isinstance(plugin.name, str)
                    or not plugin.name.strip()
                    or not isinstance(plugin.description, str)
                    or not plugin.description.strip()
                ):
                    raise ValueError("Plugin name and description are required")

                plugin_ids.add(plugin.plugin_id)
                self.plugins.append(plugin)
            except Exception as error:
                self.errors.append((
                    module_name, f"{type(error).__name__}: {error}"
                ))

        self.plugins.sort(key=lambda plugin: (plugin.order, plugin.name))
        return self.plugins
