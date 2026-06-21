import csv
import datetime
import os
import tempfile
import zipfile
from collections import Counter

from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPdfWriter, QPageSize

from .cache import cache_dir
from .helpers import _find_tsv

_IUCN_ORDER = ["EX", "EW", "CR", "EN", "VU", "NT", "LC", "DD", "NE"]
_IUCN_COLOR = {
    "EX": "#1a1a1a", "EW": "#4b0a2f", "CR": "#cc0000",
    "EN": "#e65c00", "VU": "#d4a800", "NT": "#57a337",
    "LC": "#78c679", "DD": "#aaaaaa", "NE": "#cccccc",
}
_IUCN_LABEL = {
    "EX": "Extinct",           "EW": "Extinct in the Wild",
    "CR": "Critically Endangered", "EN": "Endangered",
    "VU": "Vulnerable",        "NT": "Near Threatened",
    "LC": "Least Concern",     "DD": "Data Deficient",
    "NE": "Not Evaluated",
}

_DPI    = 150
_MM_PX  = _DPI / 25.4
_MARGIN = int(15 * _MM_PX)
_W      = int(210 * _MM_PX) - 2 * _MARGIN
_TITLE_BOTTOM_PADDING = 30
_SECTION_PADDING = 50
_PIE_COLORS = [
    "#4e79a7", "#f28e6b", "#76b7b2", "#af7aa1", "#edc76f",
    "#59a14f", "#9c755f", "#6f8fd2", "#d887b5", "#86bc86",
]


class ReportWorker(QThread):
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, key: str, download_link: str):
        super().__init__()
        self._key  = key
        self._link = download_link

    def run(self):
        tmp_tsv = None
        try:
            self.progress.emit("Fetching data…")
            tsv_path, tmp_tsv = self._get_tsv()
            self.progress.emit("Parsing records…")
            stats = self._parse(tsv_path)
            self.progress.emit("Rendering PDF…")
            out_dir = cache_dir() / self._key
            out_dir.mkdir(exist_ok=True)
            out_path = str(out_dir / "report.pdf")
            _render_pdf(self._key, stats, out_path)
            self.finished.emit(out_path)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if tmp_tsv and os.path.exists(tmp_tsv):
                os.unlink(tmp_tsv)

    def _get_tsv(self):
        import urllib.request
        from .cache import cache_dir

        cached_tsv = os.path.join(tempfile.gettempdir(), f"{self._key}.tsv")
        if os.path.exists(cached_tsv):
            return cached_tsv, None

        # Reuse cached zip if "Save ZIP" was already run
        cached_zip = cache_dir() / self._key / "download.zip"

        if not cached_zip.exists():
            self.progress.emit("Downloading data…")
            cached_zip.parent.mkdir(exist_ok=True)
            with urllib.request.urlopen(self._link, timeout=120) as resp:
                with open(str(cached_zip), "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)

        tmp_tsv_fd, tmp_tsv = tempfile.mkstemp(suffix=".tsv")
        os.close(tmp_tsv_fd)
        try:
            with zipfile.ZipFile(str(cached_zip)) as zf:
                name = _find_tsv(zf)
                with zf.open(name) as src, open(tmp_tsv, "wb") as dst:
                    dst.write(src.read())
            return tmp_tsv, tmp_tsv
        except Exception:
            if os.path.exists(tmp_tsv):
                os.unlink(tmp_tsv)
            raise

    def _parse(self, tsv_path: str) -> dict:
        year_counts    = Counter()
        iucn_counts    = Counter()
        iucn_year_counts = Counter()
        species_counts = Counter()
        country_counts = Counter()
        basis_counts   = Counter()
        total = 0

        with open(tsv_path, encoding="utf-8", newline="", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            fieldnames = reader.fieldnames or []
            norm = {fn.lower(): fn for fn in fieldnames}
            year_f    = norm.get("year", "")
            iucn_f    = norm.get("iucnredlistcategory", "")
            species_f = norm.get("species", "")
            country_f = norm.get("countrycode", "")
            basis_f   = norm.get("basisofrecord", "")

            for row in reader:
                total += 1
                yr = (row.get(year_f) or "").strip() if year_f else ""
                if yr.isdigit():
                    year_counts[int(yr)] += 1
                iucn = (row.get(iucn_f) or "").strip().upper() if iucn_f else ""
                if iucn:
                    iucn_counts[iucn] += 1
                    if yr.isdigit():
                        iucn_year_counts[(int(yr), iucn)] += 1
                sp = (row.get(species_f) or "").strip() if species_f else ""
                if sp:
                    species_counts[sp] += 1
                cc = (row.get(country_f) or "").strip() if country_f else ""
                if cc:
                    country_counts[cc] += 1
                bor = (row.get(basis_f) or "").strip() if basis_f else ""
                if bor:
                    basis_counts[bor] += 1

        return {
            "total":            total,
            "unique_species":   len(species_counts),
            "unique_countries": len(country_counts),
            "year_range":       (min(year_counts) if year_counts else None,
                                 max(year_counts) if year_counts else None),
            "year_counts":      year_counts,
            "iucn_counts":      iucn_counts,
            "iucn_year_counts": iucn_year_counts,
            "top_species":      species_counts.most_common(10),
            "top_countries":    country_counts.most_common(10),
            "basis_counts":     basis_counts,
        }


# ── PDF rendering ─────────────────────────────────────────────────────────────

def _render_pdf(key: str, stats: dict, out_path: str):
    writer = QPdfWriter(out_path)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setResolution(_DPI)

    p = QPainter(writer)
    p.translate(_MARGIN, _MARGIN)
    try:
        _draw_report(p, key, stats)
    finally:
        p.end()


def _draw_report(p: QPainter, key: str, stats: dict):
    W = _W
    y = 0

    p.setFont(QFont("Arial", 16, QFont.Bold))
    p.setPen(QColor("#1a3a6b"))
    p.drawText(0, y, W, 42, Qt.AlignLeft | Qt.AlignVCenter, "GBIF Occurrence Report")
    y += 42 + _TITLE_BOTTOM_PADDING

    p.setFont(QFont("Arial", 8))
    p.setPen(QColor("#888888"))
    meta = f"Key: {key}   ·   Generated: {datetime.date.today().isoformat()}"
    p.drawText(0, y, W, 18, Qt.AlignLeft | Qt.AlignVCenter, meta)
    y += 20

    _hline(p, W, y); y += _SECTION_PADDING

    y = _draw_summary_cards(p, W, y, stats)
    _hline(p, W, y); y += _SECTION_PADDING

    y = _draw_year_chart(p, W, y, stats)
    _hline(p, W, y); y += _SECTION_PADDING

    y = _draw_iucn_charts(p, W, y, stats)
    _hline(p, W, y); y += _SECTION_PADDING

    _draw_bottom_cols(p, W, y, stats)


def _hline(p: QPainter, W: int, y: int):
    p.setPen(QColor("#dddddd"))
    p.drawLine(0, y, W, y)


def _section_title(p: QPainter, W: int, y: int, text: str) -> int:
    p.setFont(QFont("Arial", 10, QFont.Bold))
    p.setPen(QColor("#333333"))
    p.drawText(0, y, W, 22, Qt.AlignLeft | Qt.AlignVCenter, text)
    return y + 24 + _TITLE_BOTTOM_PADDING


def _draw_summary_cards(p: QPainter, W: int, y: int, stats: dict) -> int:
    y = _section_title(p, W, y, "Summary")

    yr = stats["year_range"]
    yr_str = f"{yr[0]} – {yr[1]}" if yr[0] else "—"
    cards = [
        ("Total Records",  f"{stats['total']:,}"),
        ("Unique Species", f"{stats['unique_species']:,}"),
        ("Countries",      f"{stats['unique_countries']:,}"),
        ("Year Range",     yr_str),
    ]

    gap = 8
    cw  = (W - 3 * gap) // 4
    ch  = 54

    for i, (label, value) in enumerate(cards):
        x = i * (cw + gap)
        p.setBrush(QColor("#f0f4f9"))
        p.setPen(QColor("#c0d0e0"))
        p.drawRect(x, y, cw, ch)
        p.setFont(QFont("Arial", 13, QFont.Bold))
        p.setPen(QColor("#1a3a6b"))
        p.drawText(x + 8, y + 4, cw - 16, 30, Qt.AlignLeft | Qt.AlignVCenter, value)
        p.setFont(QFont("Arial", 7))
        p.setPen(QColor("#778899"))
        p.drawText(x + 8, y + 34, cw - 16, 16, Qt.AlignLeft | Qt.AlignVCenter, label)

    p.setBrush(Qt.NoBrush)
    return y + ch + 14


def _draw_year_chart(p: QPainter, W: int, y: int, stats: dict) -> int:
    y = _section_title(p, W, y, "Occurrences by Year")
    yc = stats["year_counts"]

    if not yc:
        p.setFont(QFont("Arial", 8))
        p.setPen(QColor("#888888"))
        p.drawText(0, y, W, 18, Qt.AlignLeft | Qt.AlignVCenter, "No year data available.")
        return y + 20

    CH     = 130
    Y_LBL  = 52
    cw     = W - Y_LBL
    years  = sorted(yc)
    mx     = max(yc.values())
    n      = len(years)
    bw     = max(1, (cw - n) // n)
    tot_w  = n * (bw + 1)

    p.setFont(QFont("Arial", 7))
    for frac, lbl in [(1.0, f"{mx:,}"), (0.5, f"{mx // 2:,}"), (0.0, "0")]:
        gy = y + int(CH * (1.0 - frac))
        p.setPen(QColor("#eeeeee"))
        p.drawLine(Y_LBL, gy, Y_LBL + tot_w, gy)
        p.setPen(QColor("#888888"))
        p.drawText(0, gy - 8, Y_LBL - 4, 16, Qt.AlignRight | Qt.AlignVCenter, lbl)

    p.setPen(Qt.NoPen)
    for i, yr in enumerate(years):
        bh = max(1, int(CH * yc[yr] / mx))
        bx = Y_LBL + i * (bw + 1)
        p.setBrush(QColor("#4a90d9"))
        p.drawRect(bx, y + CH - bh, bw, bh)

    p.setBrush(Qt.NoBrush)
    p.setPen(QColor("#aaaaaa"))
    p.drawLine(Y_LBL, y, Y_LBL, y + CH)
    p.drawLine(Y_LBL, y + CH, Y_LBL + tot_w, y + CH)

    step = max(1, n // 10)
    p.setFont(QFont("Arial", 7))
    p.setPen(QColor("#666666"))
    for i, yr in enumerate(years):
        if i % step == 0:
            bx = Y_LBL + i * (bw + 1) + bw // 2
            p.drawText(bx - 15, y + CH + 2, 30, 14, Qt.AlignCenter, str(yr))

    return y + CH + 20


def _draw_iucn_charts(p: QPainter, W: int, y: int, stats: dict) -> int:
    ic = stats["iucn_counts"]
    iyc = stats["iucn_year_counts"]

    present = [(cat, ic[cat]) for cat in _IUCN_ORDER if ic.get(cat, 0) > 0]
    if not present:
        y = _section_title(p, W, y, "IUCN Conservation Status")
        p.setFont(QFont("Arial", 8))
        p.setPen(QColor("#888888"))
        p.drawText(0, y, W, 18, Qt.AlignLeft | Qt.AlignVCenter, "No IUCN data in this download.")
        return y + 22

    gap = 24
    year_w = int(W * 0.66)
    pie_x = year_w + gap
    pie_w = W - pie_x

    p.setFont(QFont("Arial", 10, QFont.Bold))
    p.setPen(QColor("#333333"))
    p.drawText(0, y, year_w, 22, Qt.AlignLeft | Qt.AlignVCenter, "Conservation Status by Year")
    p.drawText(pie_x, y, pie_w, 22, Qt.AlignLeft | Qt.AlignVCenter, "Overall Conservation Status")
    y += 24 + _TITLE_BOTTOM_PADDING

    chart_h = 130
    axis_w = 44
    present_cats = [cat for cat, _ in present]
    years = sorted({year for year, cat in iyc if cat in present_cats})
    year_totals = {
        year: sum(iyc[(year, cat)] for cat, _ in present)
        for year in years
    }
    max_total = max(year_totals.values(), default=0)
    chart_w = year_w - axis_w

    if years and max_total:
        bar_step = chart_w / len(years)
        bar_w = max(1, int(bar_step) - 1)
        p.setFont(QFont("Arial", 7))
        for frac, label in [(1.0, f"{max_total:,}"), (0.5, f"{max_total // 2:,}"), (0.0, "0")]:
            grid_y = y + int(chart_h * (1.0 - frac))
            p.setPen(QColor("#eeeeee"))
            p.drawLine(axis_w, grid_y, year_w, grid_y)
            p.setPen(QColor("#888888"))
            p.drawText(0, grid_y - 8, axis_w - 4, 16, Qt.AlignRight | Qt.AlignVCenter, label)

        for i, year in enumerate(years):
            bar_x = axis_w + int(i * bar_step)
            bar_bottom = y + chart_h
            cumulative = 0
            for cat, _ in present:
                count = iyc[(year, cat)]
                if not count:
                    continue
                next_cumulative = cumulative + count
                segment_h = (
                    round(chart_h * next_cumulative / max_total)
                    - round(chart_h * cumulative / max_total)
                )
                cumulative = next_cumulative
                if segment_h <= 0:
                    continue
                bar_bottom -= segment_h
                p.setBrush(QColor(_IUCN_COLOR[cat]))
                p.setPen(Qt.NoPen)
                p.drawRect(bar_x, bar_bottom, bar_w, segment_h)

        p.setBrush(Qt.NoBrush)
        p.setPen(QColor("#aaaaaa"))
        p.drawLine(axis_w, y, axis_w, y + chart_h)
        p.drawLine(axis_w, y + chart_h, year_w, y + chart_h)

        label_step = max(1, len(years) // 8)
        p.setFont(QFont("Arial", 7))
        p.setPen(QColor("#666666"))
        for i, year in enumerate(years):
            if i % label_step == 0:
                label_x = axis_w + int((i + 0.5) * bar_step)
                p.drawText(label_x - 18, y + chart_h + 2, 36, 14, Qt.AlignCenter, str(year))
    else:
        p.setFont(QFont("Arial", 8))
        p.setPen(QColor("#888888"))
        p.drawText(0, y, year_w, chart_h, Qt.AlignCenter, "No year data available.")

    total = sum(count for _, count in present)
    pie_size = min(chart_h, pie_w)
    pie_left = pie_x + (pie_w - pie_size) // 2
    start_angle = 90 * 16
    for i, (cat, count) in enumerate(present):
        if i == len(present) - 1:
            span_angle = (90 * 16 - 360 * 16) - start_angle
        else:
            span_angle = -round(360 * 16 * count / total)
        p.setBrush(QColor(_IUCN_COLOR[cat]))
        p.setPen(QColor("#ffffff"))
        p.drawPie(pie_left, y, pie_size, pie_size, start_angle, span_angle)
        start_angle += span_angle

    legend_y = y + chart_h + 22
    columns = 3
    column_w = W // columns
    row_h = 18
    for i, (cat, count) in enumerate(present):
        col = i % columns
        row = i // columns
        item_x = col * column_w
        item_y = legend_y + row * row_h
        p.setBrush(QColor(_IUCN_COLOR[cat]))
        p.setPen(Qt.NoPen)
        p.drawRect(item_x, item_y + 4, 10, 10)
        label = f"{cat}  {_IUCN_LABEL.get(cat, cat)}  {count:,}"
        p.setFont(QFont("Arial", 7))
        p.setPen(QColor("#444444"))
        p.drawText(item_x + 15, item_y, column_w - 20, row_h, Qt.AlignLeft | Qt.AlignVCenter, label)

    p.setBrush(Qt.NoBrush)
    legend_rows = (len(present) + columns - 1) // columns
    return legend_y + legend_rows * row_h + 8


def _draw_bottom_cols(p: QPainter, W: int, y: int, stats: dict):
    half = (W - 16) // 2
    _draw_pie_col(p, 0,          half, y, "Top Species",   stats["top_species"])
    _draw_pie_col(p, half + 16,  half, y, "Top Countries", stats["top_countries"])


def _draw_pie_col(p: QPainter, x: int, W: int, y: int, title: str, data: list):
    p.setFont(QFont("Arial", 10, QFont.Bold))
    p.setPen(QColor("#333333"))
    p.drawText(x, y, W, 22, Qt.AlignLeft | Qt.AlignVCenter, title)
    y += 24 + _TITLE_BOTTOM_PADDING

    if not data:
        p.setFont(QFont("Arial", 8))
        p.setPen(QColor("#888888"))
        p.drawText(x, y, W, 18, Qt.AlignLeft | Qt.AlignVCenter, "No data.")
        return

    total = sum(cnt for _, cnt in data)
    pie_size = min(180, W // 3)
    pie_y = y + 2
    start_angle = 90 * 16

    for i, (_, cnt) in enumerate(data):
        if i == len(data) - 1:
            span_angle = (90 * 16 - 360 * 16) - start_angle
        else:
            span_angle = -round(360 * 16 * cnt / total)
        p.setBrush(QColor(_PIE_COLORS[i % len(_PIE_COLORS)]))
        p.setPen(QColor("#ffffff"))
        p.drawPie(x, pie_y, pie_size, pie_size, start_angle, span_angle)
        start_angle += span_angle

    legend_x = x + pie_size + 14
    legend_w = W - pie_size - 14
    row_h = 18
    swatch = 10
    p.setFont(QFont("Arial", 7))
    values = [f"{cnt:,} ({100 * cnt / total:.1f}%)" for _, cnt in data]
    value_w = max(p.fontMetrics().horizontalAdvance(value) for value in values) + 6

    for i, ((name, _), value) in enumerate(zip(data, values)):
        row_y = y + i * row_h
        color = QColor(_PIE_COLORS[i % len(_PIE_COLORS)])
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawRect(legend_x, row_y + 4, swatch, swatch)

        p.setPen(QColor("#333333"))
        name_x = legend_x + swatch + 5
        name_w = max(20, legend_w - swatch - value_w - 9)
        label = p.fontMetrics().elidedText(name, Qt.ElideRight, name_w)
        p.drawText(name_x, row_y, name_w, row_h, Qt.AlignLeft | Qt.AlignVCenter, label)
        p.setPen(QColor("#666666"))
        p.drawText(
            legend_x + legend_w - value_w,
            row_y,
            value_w,
            row_h,
            Qt.AlignRight | Qt.AlignVCenter,
            value,
        )

    p.setBrush(Qt.NoBrush)
