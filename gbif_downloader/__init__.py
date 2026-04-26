def classFactory(iface):
    from .plugin import GbifDownloaderPlugin
    return GbifDownloaderPlugin(iface)
