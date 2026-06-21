def classFactory(iface):
    from . import compat  # noqa: F401 — patches Qt flat enum names for PyQt6
    from .plugin import GbifDownloaderPlugin
    return GbifDownloaderPlugin(iface)
