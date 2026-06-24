<h1>
  <img src="gbif-downloader-icon.png" alt="GBIF Downloader icon" width="32" height="32">
  GBIF Downloader
</h1>

A QGIS plugin for submitting and managing occurrence download requests through
the [GBIF Download API](https://www.gbif.org/developer/occurrence#download).

## Features

### Query builder

Filters are organized in collapsible accordion sections. Active sections are
highlighted; the live occurrence count updates automatically as filters change.

| Filter | Type |
|---|---|
| Scientific name | Autocomplete (GBIF species suggest) |
| Dataset | Autocomplete (GBIF dataset suggest) |
| Institution | Autocomplete (GBIF institution suggest) |
| Basis of record | Checkboxes (9 options) |
| Country | Autocomplete country list |
| Year | No filter / Between / Is / Before / After modes |
| Coordinate uncertainty | Numeric range (At most / At least / Between), metres |
| Elevation | Numeric range (At most / At least / Between), metres |
| Month | Checkboxes (Jan–Dec) |
| Conservation status (IUCN) | Checkboxes (EX, EW, CR, EN, VU, NT, LC, DD, NE) |
| Geometry | Draw polygon on map canvas or use an existing polygon layer |

A **Clear All Filters** button resets all sections at once. Before submitting,
a summary dialog shows the full predicate and requires acceptance of the GBIF
data use agreement and citation requirements.

### Downloads manager

- Paginated list of past and pending downloads (50 per page)
- Filter by status and submission date
- Automatic background polling until pending downloads complete
- Per-download actions:
  - **Load as layer** — adds occurrence data directly to the QGIS map
  - **Save ZIP** — downloads the archive to a local cache folder
  - **Details** — shows full metadata (format, record count, datasets, size,
    DOI, licence, expiry date, citation text with RIS/BibTeX export links,
    and a breakdown of all predicate filters used)
  - **Report** — generates and opens a PDF summary via GBIF's reporting API
- Geometry predicates in the details view can be loaded back to the map as
  a memory layer

### Credentials

GBIF credentials are stored in the QGIS authentication manager. A **Configure
GBIF Credentials** button appears inline whenever credentials are missing.

## Requirements

- QGIS 3.28 or newer (including QGIS 4.x / Qt 6)
- A [GBIF account](https://www.gbif.org/user/profile)

No separate Python packages are required — the plugin uses only modules
bundled with QGIS.

## Installation

### From ZIP (recommended)

1. Run `make package` to produce `dist/gbif_downloader.zip`.
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**.

### Development

Clone into the QGIS profile's plugin directory so it can be loaded directly:

```bash
# QGIS 3 (macOS)
git clone https://github.com/dimasciputra/gbif-project-2026.git \
  ~/Library/Application\ Support/QGIS/QGIS3/profiles/default/python/plugins/gbif_downloader

# QGIS 4 (macOS)
git clone https://github.com/dimasciputra/gbif-project-2026.git \
  ~/Library/Application\ Support/QGIS/QGIS4/profiles/default/python/plugins/gbif_downloader
```

Restart QGIS and enable **GBIF Downloader** under
**Plugins → Manage and Install Plugins → Installed**.

## Build

```bash
make          # build dist/gbif_downloader.zip
make check    # build and verify the archive
make clean    # remove build/ and dist/
```

## Repository layout

```text
.
├── __init__.py            entry point; imports compat before anything else
├── metadata.txt
├── plugin.py              toolbar action and dock setup
├── dock_widget.py         two-tab dock (Query builder + Downloads)
├── compat.py              PyQt5→PyQt6 enum shim for QGIS 4 compatibility
├── credentials_dialog.py  GBIF credential management dialog
├── gbif_api.py            GBIF REST helpers and credential storage
├── gui/                   Qt Designer .ui files
├── tab_action/            query builder tab
│   ├── action_tab.py      main widget; wires filters → predicate → submit
│   ├── accordion.py       collapsible filter section base classes
│   ├── styles.py          shared stylesheet constants
│   ├── predicate.py       GBIF predicate builder and formatter
│   ├── autocomplete_section.py  base class for autocomplete filters
│   ├── scientific_name_filter.py
│   ├── taxon_filter.py    higher-taxonomy filter (Family / Order / Class)
│   ├── dataset_filter.py
│   ├── institution_filter.py
│   ├── country_filter.py
│   ├── geometry_filter.py draw-on-canvas or layer geometry filter
│   ├── polygon_tool.py    QGIS map tool for polygon capture
│   └── worker.py          background thread for download submission
└── tab_downloads/         downloads manager tab
    ├── downloads_tab.py   main widget; fetch, poll, filter, paginate
    ├── widgets.py         DownloadItemWidget, DetailDialog, FilterItemWidget
    ├── workers.py         FetchPageWorker, PollWorker, DownloadWorker
    ├── report_worker.py   PDF report generation worker
    ├── helpers.py         status colours, predicate → rows, formatting
    ├── styling.py         IUCN-based QGIS layer symbology
    └── cache.py           local JSON cache for downloads and page results
```

## License

This project is licensed under the GPL-3.0 License.
