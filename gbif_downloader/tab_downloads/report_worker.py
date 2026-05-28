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
_MARGIN = int(15 * _MM_PX)          # ≈ 89 px
_W      = int(210 * _MM_PX) - 2 * _MARGIN   # ≈ 1062 px


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
        cached = os.path.join(tempfile.gettempdir(), f"{self._key}.tsv")
        if os.path.exists(cached):
            return cached, None

        tmp_zip_fd, tmp_zip = tempfile.mkstemp(suffix=".zip")
        os.close(tmp_zip_fd)
        tmp_tsv_fd, tmp_tsv = tempfile.mkstemp(suffix=".tsv")
        os.close(tmp_tsv_fd)
        try:
            with urllib.request.urlopen(self._link, timeout=120) as resp:
                with open(tmp_zip, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
            with zipfile.ZipFile(tmp_zip) as zf:
                name = _find_tsv(zf)
                with zf.open(name) as src, open(tmp_tsv, "wb") as dst:
                    dst.write(src.read())
            return tmp_tsv, tmp_tsv
        except Exception:
            if os.path.exists(tmp_tsv):
                os.unlink(tmp_tsv)
            raise
        finally:
            if os.path.exists(tmp_zip):
                os.unlink(tmp_zip)

    def _parse(self, tsv_path: str) -> dict:
        year_counts    = Counter()
        iucn_counts    = Counter()
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
    y += 42

    p.setFont(QFont("Arial", 8))
    p.setPen(QColor("#888888"))
    meta = f"Key: {key}   ·   Generated: {datetime.date.today().isoformat()}"
    p.drawText(0, y, W, 18, Qt.AlignLeft | Qt.AlignVCenter, meta)
    y += 20

    _hline(p, W, y); y += 14

    y = _draw_summary_cards(p, W, y, stats)
    _hline(p, W, y); y += 14

    y = _draw_year_chart(p, W, y, stats)
    _hline(p, W, y); y += 14

    y = _draw_iucn_chart(p, W, y, stats)
    _hline(p, W, y); y += 14

    _draw_bottom_cols(p, W, y, stats)


def _hline(p: QPainter, W: int, y: int):
    p.setPen(QColor("#dddddd"))
    p.drawLine(0, y, W, y)


def _section_title(p: QPainter, W: int, y: int, text: str) -> int:
    p.setFont(QFont("Arial", 10, QFont.Bold))
    p.setPen(QColor("#333333"))
    p.drawText(0, y, W, 22, Qt.AlignLeft | Qt.AlignVCenter, text)
    return y + 24


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
        p.drawRoundedRect(x, y, cw, ch, 4, 4)
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


def _draw_iucn_chart(p: QPainter, W: int, y: int, stats: dict) -> int:
    y = _section_title(p, W, y, "IUCN Conservation Status")
    ic = stats["iucn_counts"]

    present = [(cat, ic[cat]) for cat in _IUCN_ORDER if ic.get(cat, 0) > 0]
    if not present:
        p.setFont(QFont("Arial", 8))
        p.setPen(QColor("#888888"))
        p.drawText(0, y, W, 18, Qt.AlignLeft | Qt.AlignVCenter, "No IUCN data in this download.")
        return y + 22

    mx      = max(c for _, c in present)
    LBL_W   = 185
    CNT_W   = 65
    BAR_W   = W - LBL_W - CNT_W - 8
    ROW_H   = 20

    for i, (cat, cnt) in enumerate(present):
        ry    = y + i * ROW_H
        color = QColor(_IUCN_COLOR.get(cat, "#cccccc"))
        lbl   = f"{cat}  —  {_IUCN_LABEL.get(cat, cat)}"

        p.setFont(QFont("Arial", 8))
        p.setPen(QColor("#444444"))
        p.drawText(0, ry, LBL_W - 6, ROW_H, Qt.AlignRight | Qt.AlignVCenter, lbl)

        bw = max(2, int(BAR_W * cnt / mx)) if mx else 2
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawRect(LBL_W, ry + 4, bw, ROW_H - 8)

        p.setPen(QColor("#555555"))
        p.setFont(QFont("Arial", 7))
        p.drawText(LBL_W + bw + 4, ry, CNT_W, ROW_H, Qt.AlignLeft | Qt.AlignVCenter, f"{cnt:,}")

    p.setBrush(Qt.NoBrush)
    return y + len(present) * ROW_H + 10


def _draw_bottom_cols(p: QPainter, W: int, y: int, stats: dict):
    half = (W - 16) // 2
    _draw_bar_col(p, 0,          half, y, "Top Species",   stats["top_species"])
    _draw_bar_col(p, half + 16,  half, y, "Top Countries", stats["top_countries"])


def _draw_bar_col(p: QPainter, x: int, W: int, y: int, title: str, data: list):
    p.setFont(QFont("Arial", 10, QFont.Bold))
    p.setPen(QColor("#333333"))
    p.drawText(x, y, W, 22, Qt.AlignLeft | Qt.AlignVCenter, title)
    y += 24

    if not data:
        p.setFont(QFont("Arial", 8))
        p.setPen(QColor("#888888"))
        p.drawText(x, y, W, 18, Qt.AlignLeft | Qt.AlignVCenter, "No data.")
        return

    mx     = data[0][1]
    LBL_W  = int(W * 0.40)
    BAR_W  = int(W * 0.42)
    CNT_W  = W - LBL_W - BAR_W - 4
    ROW_H  = 18

    for name, cnt in data:
        p.setFont(QFont("Arial", 7))
        p.setPen(QColor("#333333"))
        p.drawText(x, y, LBL_W - 4, ROW_H, Qt.AlignRight | Qt.AlignVCenter, name[:25])

        bw = max(2, int(BAR_W * cnt / mx)) if mx else 2
        p.setBrush(QColor("#4a90d9"))
        p.setPen(Qt.NoPen)
        p.drawRect(x + LBL_W, y + 3, bw, ROW_H - 6)

        p.setPen(QColor("#555555"))
        p.setFont(QFont("Arial", 7))
        p.drawText(x + LBL_W + bw + 3, y, CNT_W, ROW_H, Qt.AlignLeft | Qt.AlignVCenter, f"{cnt:,}")

        y += ROW_H

    p.setBrush(Qt.NoBrush)
