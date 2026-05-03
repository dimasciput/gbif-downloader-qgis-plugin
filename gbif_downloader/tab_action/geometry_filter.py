from qgis.core import (
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtWidgets import QComboBox, QLabel, QPushButton

from .accordion import AccordionSection
from .predicate import geom_to_wkt


class GeometryFilterSection(AccordionSection):
    """AccordionSection for drawn or active-layer geometry filters."""

    def __init__(self, iface, parent=None):
        super().__init__("Geometry", parent)
        self._iface = iface
        self._geometry_wkt = ""
        self._rubber_band = None
        self._on_draw_requested = None
        self._on_draw_cancel_requested = None

        layout = self.content_layout
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("No filter", "none")
        self._mode_combo.addItem("Draw polygon", "draw")
        self._mode_combo.addItem("Use existing polygon layer", "layer")

        self._layer_combo = QComboBox()
        self._draw_btn = QPushButton("Draw Polygon")
        self._load_layer_btn = QPushButton("Load Layer")
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setEnabled(False)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)

        layout.addWidget(self._mode_combo, 0, 0, 1, 2)
        layout.addWidget(self._layer_combo, 1, 0, 1, 2)
        layout.addWidget(self._draw_btn, 2, 0)
        layout.addWidget(self._load_layer_btn, 2, 0)
        layout.addWidget(self._clear_btn, 2, 1)
        layout.addWidget(self._status_label, 3, 0, 1, 2)

        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._layer_combo.currentIndexChanged.connect(self.load_existing_polygon_layer)
        self._draw_btn.clicked.connect(self._request_draw)
        self._load_layer_btn.clicked.connect(self.load_existing_polygon_layer)
        self._clear_btn.clicked.connect(self.clear_geometry)
        self._on_mode_changed()

    def set_draw_handlers(self, on_draw_requested, on_draw_cancel_requested):
        self._on_draw_requested = on_draw_requested
        self._on_draw_cancel_requested = on_draw_cancel_requested

    def _on_mode_changed(self):
        mode = self._mode_combo.currentData()
        is_draw_mode = mode == "draw"
        is_layer_mode = mode == "layer"
        self._draw_btn.setVisible(is_draw_mode)
        self._layer_combo.setVisible(is_layer_mode)
        self._load_layer_btn.setVisible(is_layer_mode)
        self._clear_btn.setVisible(mode != "none")
        if self._on_draw_cancel_requested:
            self._on_draw_cancel_requested()
        if mode == "none":
            self.clear_geometry()
        elif is_draw_mode:
            self.clear_geometry()
        else:
            self._refresh_layer_combo()
            self.load_existing_polygon_layer()

    def _request_draw(self):
        if self._on_draw_requested:
            self._on_draw_requested()

    def set_draw_active(self, active: bool):
        self._draw_btn.setText("Cancel" if active else "Draw Polygon")

    def set_draw_prompt(self):
        self._status_label.setText(
            "Click to add vertices - right-click to close the polygon."
        )
        self._status_label.setStyleSheet("color: #555;")

    def set_draw_cancelled(self):
        self.set_draw_active(False)
        if not self._geometry_wkt:
            self._status_label.setText("")
            self._status_label.setStyleSheet("")

    def set_drawn_geometry(self, geom, canvas_crs, rubber_band):
        if self._rubber_band is not None:
            self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self._rubber_band = rubber_band
        self._geometry_wkt = geom_to_wkt(geom, canvas_crs)
        self._set_geometry_loaded("Drawn polygon loaded.")

    def load_existing_polygon_layer(self, _event=None):
        layer = self._selected_layer()
        if not self._is_polygon_layer(layer):
            self._set_geometry_error("Choose a polygon layer first.")
            return

        geometry = self._layer_geometry(layer)
        if not geometry or geometry.isEmpty():
            self._set_geometry_error("The selected polygon layer has no geometry.")
            return

        self._geometry_wkt = geom_to_wkt(geometry, layer.crs())
        self._set_geometry_loaded(f"Loaded geometry from {layer.name()}.")

    def _refresh_layer_combo(self):
        current_layer_id = self._layer_combo.currentData()
        active_layer = self._iface.activeLayer()
        active_layer_id = (
            active_layer.id() if self._is_polygon_layer(active_layer) else None
        )

        self._layer_combo.blockSignals(True)
        self._layer_combo.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if self._is_polygon_layer(layer):
                self._layer_combo.addItem(layer.name(), layer.id())

        target_layer_id = current_layer_id or active_layer_id
        if target_layer_id:
            index = self._layer_combo.findData(target_layer_id)
            if index >= 0:
                self._layer_combo.setCurrentIndex(index)
        self._layer_combo.blockSignals(False)

    def _selected_layer(self):
        layer_id = self._layer_combo.currentData()
        return QgsProject.instance().mapLayer(layer_id) if layer_id else None

    def _is_polygon_layer(self, layer) -> bool:
        if not isinstance(layer, QgsVectorLayer):
            return False
        return QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PolygonGeometry

    def _layer_geometry(self, layer: QgsVectorLayer):
        selected_ids = layer.selectedFeatureIds()
        request = QgsFeatureRequest().setFilterFids(selected_ids) if selected_ids else QgsFeatureRequest()
        geometry = QgsGeometry()
        for feature in layer.getFeatures(request):
            feature_geometry = feature.geometry()
            if feature_geometry and not feature_geometry.isEmpty():
                geometry = (
                    QgsGeometry(feature_geometry)
                    if geometry.isEmpty()
                    else geometry.combine(feature_geometry)
                )
        return geometry

    def _set_geometry_loaded(self, message: str):
        self._clear_btn.setEnabled(True)
        self.set_active(True)
        self._status_label.setText(message)
        self._status_label.setStyleSheet("color: green;")

    def _set_geometry_error(self, message: str):
        self.clear_geometry()
        self._status_label.setText(message)
        self._status_label.setStyleSheet("color: red;")

    def clear_geometry(self):
        if self._rubber_band is not None:
            self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
            self._rubber_band = None
        self._geometry_wkt = ""
        self._clear_btn.setEnabled(False)
        self.set_active(False)
        self._status_label.setText("")
        self._status_label.setStyleSheet("")

    def get_geometry_wkt(self) -> str:
        return self._geometry_wkt
