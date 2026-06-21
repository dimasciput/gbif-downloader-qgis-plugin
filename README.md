# GBIF Downloader

GBIF Downloader is a QGIS plugin for submitting and managing occurrence
download requests through the GBIF Download API.

## Features

- Build GBIF download predicates from taxon, country, year, basis-of-record,
  and geometry filters.
- Draw a polygon on the QGIS map canvas or use geometry from an existing layer.
- Submit, monitor, cancel, and open GBIF occurrence downloads.
- Load completed downloads into QGIS.
- Generate a PDF summary report for a download.
- Store GBIF credentials in the QGIS authentication manager.

## Requirements

- QGIS 3.28 or newer
- A [GBIF account](https://www.gbif.org/user/profile)

The plugin uses Python and Qt modules bundled with QGIS and has no separate
runtime dependencies.

## Development Installation

QGIS requires the plugin directory to be named `gbif_downloader`. Clone the
repository into the QGIS profile's plugin directory:

```bash
git clone https://github.com/dimasciputra/gbif-downloader-qgis-plugin.git \
  ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/gbif_downloader
```

Restart QGIS, then enable **GBIF Downloader** under
**Plugins > Manage and Install Plugins > Installed**.

## Package

Create an installable QGIS plugin archive:

```bash
make package
```

The archive is written to `dist/gbif_downloader.zip`. It can be installed from
**Plugins > Manage and Install Plugins > Install from ZIP**.

## Repository Layout

The repository root is the QGIS plugin package:

```text
.
├── __init__.py
├── metadata.txt
├── plugin.py
├── dock_widget.py
├── gbif_api.py
├── gui/
├── tab_action/
└── tab_downloads/
```

## License

No license has been specified yet.
