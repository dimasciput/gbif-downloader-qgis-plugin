from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor


class PolygonTool(QgsMapTool):
    """Click to add vertices, right-click to close and finish."""

    polygon_captured = pyqtSignal(object)  # QgsGeometry

    def __init__(self, canvas):
        super().__init__(canvas)
        self._vertices = []

        self._rb = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self._rb.setColor(QColor(255, 140, 0, 60))
        self._rb.setStrokeColor(QColor(255, 140, 0, 220))
        self._rb.setWidth(2)

        # Thin line previewing the edge from last vertex to cursor
        self._preview = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._preview.setStrokeColor(QColor(255, 140, 0, 160))
        self._preview.setWidth(1)
        self._preview.setLineStyle(Qt.DashLine)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pt = self.toMapCoordinates(event.pos())
            self._vertices.append(QgsPointXY(pt))
            self._redraw_polygon()
        elif event.button() == Qt.RightButton:
            self._finish()

    def canvasMoveEvent(self, event):
        if not self._vertices:
            return
        cursor = self.toMapCoordinates(event.pos())
        self._preview.reset(QgsWkbTypes.LineGeometry)
        self._preview.addPoint(self._vertices[-1])
        self._preview.addPoint(QgsPointXY(cursor))

    def _redraw_polygon(self):
        self._rb.reset(QgsWkbTypes.PolygonGeometry)
        for pt in self._vertices:
            self._rb.addPoint(pt)

    def _finish(self):
        self._preview.reset(QgsWkbTypes.LineGeometry)
        if len(self._vertices) >= 3:
            geom = QgsGeometry.fromPolygonXY([self._vertices])
            self.polygon_captured.emit(geom)
        else:
            self._rb.reset(QgsWkbTypes.PolygonGeometry)
        self.canvas().unsetMapTool(self)

    def rubber_band(self):
        return self._rb

    def deactivate(self):
        self._preview.reset(QgsWkbTypes.LineGeometry)
        super().deactivate()
