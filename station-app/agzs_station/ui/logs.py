"""Окна журнала событий и инцидентов пульта."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from agzs_station.application.cashier import CashierService
from agzs_station.application.views import IncidentView, JournalEntry

_SEVERITY = {"INFO": "Замечание", "WARNING": "Предупреждение", "CRITICAL": "Авария"}
_OPEN = "ещё не разобрано"
_SEEN = "кассир посмотрел"


def show_event_journal(parent: QWidget, service: CashierService) -> QDialog:
    dialog = _LogDialog(parent, "Журнал событий", service)
    dialog.reload = lambda: _fill_events(dialog, service)  # type: ignore[method-assign]
    dialog.reload()
    dialog.show()
    return dialog


def show_incidents(parent: QWidget, service: CashierService) -> QDialog:
    dialog = _LogDialog(parent, "Инциденты", service)
    accept = QPushButton("Отметить выбранное как просмотренное")
    accept.clicked.connect(lambda: _acknowledge(dialog, service))
    dialog.buttons.insertWidget(1, accept)
    dialog.reload = lambda: _fill_incidents(dialog, service)  # type: ignore[method-assign]
    dialog.reload()
    dialog.show()
    return dialog


class _LogDialog(QDialog):
    def __init__(self, parent: QWidget, title: str, service: CashierService) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 560)
        self.setObjectName("log-dialog")
        self._service = service
        self._zone = _zone(service)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        caption = QLabel(title)
        caption.setObjectName("face-name")
        self.explain = QLabel("")
        self.explain.setObjectName("dose-hint")
        _keep_compact(self.explain)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Поиск по колонке, чеку или тексту")
        self.filter.textChanged.connect(self._apply_filter)
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._paint_table()
        self.empty = QLabel("Записей нет")
        self.empty.setObjectName("dose-hint")
        _keep_compact(self.empty)
        # Забирает свободную высоту, когда таблицы нет. Иначе подписи с переносом
        # растягиваются и их текст встаёт по вертикали посередине окна.
        self._filler = QWidget()
        self._filler.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.buttons = QHBoxLayout()
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self._reload)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        self.buttons.addWidget(refresh)
        self.buttons.addStretch(1)
        self.buttons.addWidget(close)
        layout.addWidget(caption)
        layout.addWidget(self.explain)
        layout.addWidget(self.filter)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty)
        layout.addWidget(self._filler, 1)
        layout.addLayout(self.buttons)

    def _paint_table(self) -> None:
        ink = QColor("#102033")
        paper = QColor("#ffffff")
        stripe = QColor("#e7eef6")
        selected = QColor("#d6e4f5")
        palette = self.table.palette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
            palette.setColor(group, QPalette.ColorRole.Base, paper)
            palette.setColor(group, QPalette.ColorRole.AlternateBase, stripe)
            palette.setColor(group, QPalette.ColorRole.Text, ink)
            palette.setColor(group, QPalette.ColorRole.Highlight, selected)
            palette.setColor(group, QPalette.ColorRole.HighlightedText, ink)
        self.table.setPalette(palette)

    def reload(self) -> None:
        return None

    def _reload(self) -> None:
        self.reload()

    def _apply_filter(self) -> None:
        needle = self.filter.text().strip().casefold()
        visible = 0
        for row in range(self.table.rowCount()):
            parts = []
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                parts.append("" if item is None else item.text())
            hide = bool(needle) and needle not in " ".join(parts).casefold()
            self.table.setRowHidden(row, hide)
            if not hide:
                visible += 1
        self.empty.setVisible(visible == 0)
        show_table = self.table.rowCount() > 0
        self.table.setVisible(show_table)
        self._filler.setVisible(not show_table)


def _keep_compact(label: QLabel) -> None:
    """Подпись переносит строки и остаётся по высоте текста.

    Свободную высоту забирает таблица или растяжка под ней. Иначе QLabel
    с переносом делится этой высотой и ставит текст по вертикали в центр.
    """
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)


def _fill_events(dialog: _LogDialog, service: CashierService) -> None:
    dialog.explain.setText("Сначала новые записи: заказ, оплата, отпуск и состояние колонки.")
    dialog.empty.setText("В журнале пока нет событий.")
    rows = service.events()
    headers = ("Время", "Колонка", "Чек", "Событие", "Переход", "Подробность")
    body = [
        (
            _clock(row.occurred_at, dialog._zone),
            row.pump_name,
            row.sale_number,
            row.title,
            row.change,
            row.detail,
        )
        for row in rows
    ]
    _fill(dialog, headers, body, identity=[row.occurred_at for row in rows])


def _fill_incidents(dialog: _LogDialog, service: CashierService) -> None:
    dialog.explain.setText(
        "Это не журнал налива. Сюда попадают только сбои: авария колонки, "
        "счётчик пошёл назад, предоплата не сошлась с отпущенным. "
        "Обычный пуск и налив остаются в «Журнале». "
        "«Ещё не разобрано» значит, что кассир эту строку ещё не отметил."
    )
    dialog.empty.setText("Сбоев нет: ни аварии, ни расхождения по деньгам или счётчику.")
    rows = service.incidents()
    headers = ("Когда", "Что случилось", "Колонка", "Чек", "Отметка")
    body = [_incident_cells(row, dialog._zone) for row in rows]
    _fill(dialog, headers, body, identity=[row.incident_id for row in rows])


def _incident_cells(row: IncidentView, zone: str) -> tuple[str, ...]:
    kind = _SEVERITY.get(row.severity, row.severity)
    return (
        _clock(row.occurred_at, zone),
        f"{kind}. {row.message}",
        row.pump_name or "вся станция",
        row.sale_number or "без чека",
        _SEEN if row.acknowledged else _OPEN,
    )


def _acknowledge(dialog: _LogDialog, service: CashierService) -> None:
    selected = {item.row() for item in dialog.table.selectedItems()}
    for row in selected:
        marker = dialog.table.item(row, 0)
        if marker is None:
            continue
        incident_id = marker.data(Qt.ItemDataRole.UserRole)
        state = dialog.table.item(row, 4)
        if not incident_id or state is None or state.text() != _OPEN:
            continue
        service.acknowledge_incident(str(incident_id))
    dialog.reload()


def _fill(
    dialog: _LogDialog,
    headers: tuple[str, ...],
    body: list[tuple[str, ...]],
    *,
    identity: list[str],
) -> None:
    table = dialog.table
    table.setSortingEnabled(False)
    table.clear()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.setRowCount(len(body))
    for row_index, cells in enumerate(body):
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setForeground(QColor("#102033"))
            item.setBackground(QColor("#ffffff" if row_index % 2 == 0 else "#e7eef6"))
            if column == 0:
                item.setData(Qt.ItemDataRole.UserRole, identity[row_index])
            table.setItem(row_index, column, item)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
    table.resizeRowsToContents()
    dialog._apply_filter()


def _zone(service: CashierService) -> str:
    try:
        return service.station_timezone()
    except Exception:  # noqa: BLE001
        return "UTC"


def _clock(value: str, zone: str) -> str:
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value.replace("T", " ")[:19]
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    try:
        local = moment.astimezone(ZoneInfo(zone))
    except Exception:  # noqa: BLE001
        local = moment
    return local.strftime("%d.%m.%Y %H:%M:%S")
