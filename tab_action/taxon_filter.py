from qgis.PyQt.QtWidgets import QStyledItemDelegate, QStyle
from qgis.PyQt.QtCore import Qt, QSize, QRect


class AutocompleteNameDelegate(QStyledItemDelegate):
    """Paint autocomplete rows as name + taxonomic rank."""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 38))

    def paint(self, painter, option, index):
        text = index.data(Qt.DisplayRole) or ""
        name, _, rank = text.partition("\n")

        painter.save()
        self.initStyleOption(option, index)
        option.text = ""
        option.widget.style().drawControl(QStyle.CE_ItemViewItem, option, painter)

        left = option.rect.left() + 6
        width = option.rect.width() - 12
        name_rect = QRect(left, option.rect.top() + 4, width, 17)
        rank_rect = QRect(left, option.rect.top() + 21, width, 13)

        painter.setPen(option.palette.text().color())
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, name)
        if rank:
            painter.drawText(rank_rect, Qt.AlignLeft | Qt.AlignVCenter, rank)
        painter.restore()


