"""Пульт управления и индикации колонок.

Лицевая панель, клавиатура дозы, пуск и стоп собраны по принципу операторского
места АЗС. Колонки переключаются боковым списком, табло суммы и дозы одно —
у выбранной. Это не копия чужого интерфейса и не кассовый чек.
"""

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyleFactory,
    QVBoxLayout,
    QWidget,
)

from agzs_station.application.cashier import CashierService
from agzs_station.application.views import PumpView
from agzs_station.ui.indicators import face_digits, lamp_color, preset_kzt, status_caption
from agzs_station.ui.logs import show_event_journal, show_incidents

_SEGMENTS = {
    "0": "1110111",
    "1": "0010010",
    "2": "1011101",
    "3": "1011011",
    "4": "0111010",
    "5": "1101011",
    "6": "1101111",
    "7": "1010010",
    "8": "1111111",
    "9": "1111011",
    "-": "0001000",
    " ": "0000000",
}

def _light_palette() -> QPalette:
    palette = QPalette()
    ink = QColor("#102033")
    paper = QColor("#ffffff")
    palette.setColor(QPalette.ColorRole.Window, QColor("#e4ebf2"))
    palette.setColor(QPalette.ColorRole.WindowText, ink)
    palette.setColor(QPalette.ColorRole.Base, paper)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#e7eef6"))
    palette.setColor(QPalette.ColorRole.Text, ink)
    palette.setColor(QPalette.ColorRole.Button, paper)
    palette.setColor(QPalette.ColorRole.ButtonText, ink)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#4e6070"))
    muted = QColor("#5d7388")
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        palette.setColor(group, QPalette.ColorRole.Highlight, QColor("#0b3a6e"))
        palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, muted)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, muted)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, muted)
    return palette


_STYLE = """
QMainWindow, QWidget#console, QScrollArea, QStackedWidget#column-stage { background: #e4ebf2; color: #102033; }
QScrollArea#column-rail, QWidget#column-rail { background: #f4f7fb; border: none; }
QLabel { color: #102033; }
QWidget#header { background: #0b3a6e; }
QLabel#title { color: #ffffff; font-size: 20px; font-weight: 700; }
QLabel#header-note, QLabel#clock, QLabel#shift { color: #ffffff; }
QLineEdit {
    background: #ffffff; color: #102033; border: 1px solid #8aa0b8;
    border-radius: 4px; padding: 4px 8px;
    selection-background-color: #0b3a6e; selection-color: #ffffff;
}
QLabel#training-banner { background: #f3d98a; color: #3d2a04; padding: 6px 10px; font-weight: 700; }
QFrame#column-face { background: #ffffff; border: 1px solid #8aa0b8; border-radius: 10px; color: #102033; }
QFrame#column-face[selected="true"] { border: 3px solid #c4840a; background: #fff8e8; color: #102033; }
QFrame#column-switch { background: #ffffff; border: 2px solid #8aa0b8; border-radius: 8px; color: #102033; }
QFrame#column-switch[selected="true"] { border: 2px solid #c4840a; background: #fff8e8; color: #102033; }
QFrame#display { background: #062015; border: 1px solid #1d4a32; border-radius: 6px; }
QLabel#display-caption { color: #d7ffe4; font-weight: 700; background: transparent; }
QLabel#face-name { color: #102033; font-weight: 700; font-size: 14px; background: transparent; }
QLabel#face-state { color: #102033; font-weight: 700; background: transparent; }
QLabel#face-meta, QLabel#face-total { color: #243447; background: transparent; }
QWidget#deck { background: #f4f7fb; border: 1px solid #8aa0b8; border-radius: 10px; color: #102033; }
QLabel#dose-hint { color: #243447; }
QLabel#dose-entry {
    background: #062015; color: #b6ff6a; border-radius: 6px;
    font-family: Consolas, "Courier New"; font-size: 28px; font-weight: 700; padding: 4px 10px;
}
QPushButton {
    background: #ffffff; color: #102033; border: 1px solid #5d7388;
    border-radius: 6px; font-weight: 700; padding: 4px 8px;
}
QPushButton#key {
    background: #ffffff; color: #102033; border: 1px solid #5d7388; border-radius: 6px;
    font-size: 18px; font-weight: 700; min-width: 54px; min-height: 46px;
}
QPushButton#key:pressed { background: #d5e0ea; color: #102033; }
QPushButton#key:disabled { background: #d5dee6; color: #3e5164; }
QPushButton#start { background: #157a3a; color: #ffffff; font-size: 18px; font-weight: 700; min-height: 64px; border-radius: 8px; border: none; }
QPushButton#stop { background: #b42318; color: #ffffff; font-size: 18px; font-weight: 700; min-height: 64px; border-radius: 8px; border: none; }
QPushButton#reset, QPushButton#block {
    background: #ffffff; color: #102033; border: 1px solid #5d7388;
    border-radius: 6px; font-weight: 700; min-height: 36px;
}
QPushButton#mode { background: #ffffff; color: #102033; border: 1px solid #5d7388; border-radius: 6px; min-height: 34px; font-weight: 700; }
QPushButton#mode:checked { background: #0b3a6e; color: #ffffff; border: 1px solid #0b3a6e; }
QPushButton#login { background: #ffffff; color: #0b3a6e; border: none; border-radius: 4px; font-weight: 700; padding: 4px 10px; }
QLabel#message {
    background: #102033; color: #f3fff6; padding: 8px 12px;
    font-family: Consolas, "Courier New"; font-size: 14px;
}
QDialog#log-dialog { background: #ffffff; color: #102033; }
QTableWidget {
    background: #ffffff; color: #102033; gridline-color: #c5d0dc;
    alternate-background-color: #e7eef6;
    selection-background-color: #d6e4f5; selection-color: #102033;
}
QTableWidget::item { background: #ffffff; color: #102033; }
QTableWidget::item:alternate { background: #e7eef6; color: #102033; }
QTableWidget::item:selected, QTableWidget::item:alternate:selected {
    background: #d6e4f5; color: #102033;
}
QHeaderView::section { background: #0b3a6e; color: #ffffff; padding: 6px; font-weight: 700; border: none; }
QPushButton#quiet { background: transparent; color: #ffffff; border: 1px solid #d0e2f4; border-radius: 4px; padding: 4px 8px; }
QMenu { background: #ffffff; color: #102033; border: 1px solid #5d7388; padding: 4px; }
QMenu::item { background: #ffffff; color: #102033; padding: 6px 28px 6px 16px; }
QMenu::item:selected { background: #0b3a6e; color: #ffffff; }
QMenu::item:disabled { background: #ffffff; color: #5d7388; }
QMenu::separator { height: 1px; background: #c5d0dc; margin: 4px 8px; }
"""


class SegmentDisplay(QWidget):
    """Табло из сегментов, как индикатор колонки."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text
        self.setMinimumHeight(42)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_text(self, text: str) -> None:
        self._text = text
        self.setMinimumWidth(max(120, len(text) * 22))
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(max(120, len(self._text) * 22), 42)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#062015"))
        on = QColor("#b6ff6a")
        off = QColor("#1f6b42")
        cursor = 4
        top = 6
        for char in self._text:
            if char == ".":
                painter.fillRect(cursor, top + 28, 4, 4, on)
                cursor += 8
                continue
            mask = _SEGMENTS.get(char, _SEGMENTS[" "])
            _paint_digit(painter, cursor, top, mask, on, off)
            cursor += 20
        painter.end()


def _paint_digit(painter: QPainter, x: int, y: int, mask: str, on: QColor, off: QColor) -> None:
    thickness = 3
    width = 14
    height = 28
    bars = (
        (x + 2, y, width - 4, thickness),
        (x, y + 2, thickness, height // 2 - 3),
        (x + width - thickness, y + 2, thickness, height // 2 - 3),
        (x + 2, y + height // 2 - 1, width - 4, thickness),
        (x, y + height // 2 + 2, thickness, height // 2 - 4),
        (x + width - thickness, y + height // 2 + 2, thickness, height // 2 - 4),
        (x + 2, y + height - thickness, width - 4, thickness),
    )
    for lit, bar in zip(mask, bars, strict=True):
        painter.fillRect(*bar, on if lit == "1" else off)


def _paint_status(name: QLabel, state: QLabel, lamp: QLabel, pump: PumpView) -> None:
    caption = status_caption(pump.status, pump.observation_quality)
    name.setText(pump.name.upper())
    state.setText(caption)
    lamp.setStyleSheet(f"background: {lamp_color(caption)}; border-radius: {lamp.width() // 2}px;")


class ColumnSwitch(QFrame):
    """Строка бокового списка: лампа, имя и короткие цифры, без большого табло."""

    def __init__(self, pump_id: str) -> None:
        super().__init__()
        self.pump_id = pump_id
        self.setObjectName("column-switch")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.lamp = QLabel("")
        self.lamp.setFixedSize(12, 12)
        self.name = QLabel("КОЛОНКА")
        self.name.setObjectName("face-name")
        self.state = QLabel("НЕТ СВЯЗИ")
        self.state.setObjectName("face-state")
        self.state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.lamp)
        head.addWidget(self.name, 1)
        head.addWidget(self.state)
        self.readout = QLabel("------ тг · ----.-- л")
        self.readout.setObjectName("face-meta")
        layout.addLayout(head)
        layout.addWidget(self.readout)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.selected_callback(self.pump_id)
        super().mousePressEvent(event)

    def selected_callback(self, pump_id: str) -> None:
        del pump_id

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def show_pump(self, pump: PumpView, money: str, volume: str) -> None:
        _paint_status(self.name, self.state, self.lamp, pump)
        self.readout.setText(f"{money} тг · {volume} л")


class ColumnFace(QFrame):
    def __init__(self, pump_id: str) -> None:
        super().__init__()
        self.pump_id = pump_id
        self.setObjectName("column-face")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        head = QHBoxLayout()
        self.name = QLabel("КОЛОНКА")
        self.name.setObjectName("face-name")
        self.lamp = QLabel("")
        self.lamp.setFixedSize(14, 14)
        self.state = QLabel("НЕТ СВЯЗИ")
        self.state.setObjectName("face-state")
        self.state.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.name)
        head.addStretch(1)
        head.addWidget(self.lamp)
        head.addWidget(self.state)
        layout.addLayout(head)
        display = QFrame()
        display.setObjectName("display")
        display.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        display_layout = QVBoxLayout(display)
        display_layout.setContentsMargins(8, 6, 8, 6)
        money_caption = QLabel("СУММА, тг")
        money_caption.setObjectName("display-caption")
        self.money = SegmentDisplay("000000")
        volume_caption = QLabel("ДОЗА, л")
        volume_caption.setObjectName("display-caption")
        self.volume = SegmentDisplay("0000.00")
        display_layout.addWidget(money_caption)
        display_layout.addWidget(self.money)
        display_layout.addWidget(volume_caption)
        display_layout.addWidget(self.volume)
        layout.addWidget(display)
        self.price = QLabel("цена —")
        self.price.setObjectName("face-meta")
        self.totalizer = QLabel("счётчик —")
        self.totalizer.setObjectName("face-total")
        layout.addWidget(self.price)
        layout.addWidget(self.totalizer)
        layout.addStretch(1)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.selected_callback(self.pump_id)
        super().mousePressEvent(event)

    def selected_callback(self, pump_id: str) -> None:
        del pump_id

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def show_pump(self, pump: PumpView, money: str, volume: str) -> None:
        _paint_status(self.name, self.state, self.lamp, pump)
        self.money.set_text(money)
        self.volume.set_text(volume)
        self.price.setText(f"цена {pump.price_kzt_per_liter} тг/л")
        if pump.totalizer_ml is None:
            self.totalizer.setText("счётчик скрыт")
        else:
            whole = pump.totalizer_ml // 1000
            hundredths = (pump.totalizer_ml % 1000) // 10
            self.totalizer.setText(f"счётчик {whole:06d}.{hundredths:02d} л")


class ConsoleWindow(QMainWindow):
    def __init__(self, service: CashierService, env: str) -> None:
        super().__init__()
        self._service = service
        self._env = env
        self._faces: dict[str, ColumnFace] = {}
        self._switches: dict[str, ColumnSwitch] = {}
        self._order: list[str] = []
        self._selected: str | None = None
        self._buffer = ""
        self._mode = "money"
        self._memory: dict[str, tuple[int | None, int | None]] = {}
        self._addresses: dict[str, str] = {}
        self._logs: dict[str, object] = {}
        self.setWindowTitle("AGZS — пульт колонок")
        self.resize(1080, 720)
        application = QApplication.instance()
        if application is not None:
            if "Fusion" in QStyleFactory.keys():
                application.setStyle("Fusion")
            application.setPalette(_light_palette())
            application.setStyleSheet(_STYLE)
        self.setStyleSheet(_STYLE)
        root = QWidget()
        root.setObjectName("console")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self._build_header())
        if env != "production":
            banner = QLabel("Пульт колонок. Сейчас колонки считает эмулятор: живого звена АСКА нет. Kaspi и чек Webkassa ещё не подключены.")
            banner.setObjectName("training-banner")
            layout.addWidget(banner)
        rail_host = QWidget()
        rail_host.setObjectName("column-rail")
        rail_host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        rail_box = QVBoxLayout(rail_host)
        rail_box.setContentsMargins(8, 8, 8, 8)
        rail_box.setSpacing(8)
        rail_caption = QLabel("Колонки")
        rail_caption.setObjectName("face-name")
        self._rail = QVBoxLayout()
        self._rail.setSpacing(6)
        rail_box.addWidget(rail_caption)
        rail_box.addLayout(self._rail)
        rail_box.addStretch(1)
        rail_scroll = QScrollArea()
        rail_scroll.setObjectName("column-rail")
        rail_scroll.setWidgetResizable(True)
        rail_scroll.setWidget(rail_host)
        rail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rail_scroll.setFixedWidth(280)
        self._stage = QStackedWidget()
        self._stage.setObjectName("column-stage")
        main = QVBoxLayout()
        main.setSpacing(10)
        main.addWidget(self._stage, 1)
        main.addWidget(self._build_deck())
        work = QHBoxLayout()
        work.setSpacing(10)
        work.addWidget(rail_scroll)
        work.addLayout(main, 1)
        layout.addLayout(work, 1)
        self.message = QLabel("Войдите, чтобы открыть смену и увидеть колонки.")
        self.message.setObjectName("message")
        layout.addWidget(self.message)
        if service.training:
            layout.addWidget(self._build_training())
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(200)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        row = QHBoxLayout(header)
        title = QLabel("ПУЛЬТ УПРАВЛЕНИЯ")
        title.setObjectName("title")
        note = QLabel("Колонки")
        note.setObjectName("header-note")
        self.login_name = QLineEdit()
        self.login_name.setObjectName("login-name")
        self.login_name.setPlaceholderText("Имя")
        self.login_name.setFixedWidth(120)
        self.login_password = QLineEdit()
        self.login_password.setObjectName("login-password")
        self.login_password.setPlaceholderText("Пароль")
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_password.setFixedWidth(120)
        enter = QPushButton("Вход")
        enter.setObjectName("login")
        enter.clicked.connect(self._login)
        self.shift = QLabel("Смена закрыта")
        self.shift.setObjectName("shift")
        close = QPushButton("Закрыть смену")
        close.setObjectName("quiet")
        close.clicked.connect(self._close_shift)
        journal = QPushButton("Журнал")
        journal.setObjectName("quiet")
        journal.clicked.connect(self._history)
        incidents = QPushButton("Инциденты")
        incidents.setObjectName("quiet")
        incidents.clicked.connect(self._incidents)
        self.clock = QLabel("--:--:--")
        self.clock.setObjectName("clock")
        row.addWidget(title)
        row.addWidget(note)
        row.addStretch(1)
        row.addWidget(self.login_name)
        row.addWidget(self.login_password)
        row.addWidget(enter)
        row.addWidget(self.shift)
        row.addWidget(close)
        row.addWidget(journal)
        row.addWidget(incidents)
        row.addWidget(self.clock)
        return header

    def _build_deck(self) -> QWidget:
        deck = QWidget()
        deck.setObjectName("deck")
        row = QHBoxLayout(deck)
        order = QVBoxLayout()
        caption = QLabel("ДОЗА")
        caption.setObjectName("face-name")
        self.dose_entry = QLabel("0")
        self.dose_entry.setObjectName("dose-entry")
        self.dose_entry.setMinimumWidth(220)
        self.dose_hint = QLabel("Режим: сумма, тенге")
        self.dose_hint.setObjectName("dose-hint")
        modes = QHBoxLayout()
        self._modes = QButtonGroup(self)
        money = QPushButton("Сумма")
        money.setObjectName("mode")
        money.setCheckable(True)
        money.setChecked(True)
        volume = QPushButton("Литры")
        volume.setObjectName("mode")
        volume.setCheckable(True)
        self._modes.addButton(money)
        self._modes.addButton(volume)
        money.clicked.connect(lambda: self._set_mode("money"))
        volume.clicked.connect(lambda: self._set_mode("volume"))
        modes.addWidget(money)
        modes.addWidget(volume)
        order.addWidget(caption)
        order.addWidget(self.dose_entry)
        order.addWidget(self.dose_hint)
        order.addLayout(modes)
        row.addLayout(order, 1)
        keys = QGridLayout()
        labels = ("7", "8", "9", "4", "5", "6", "1", "2", "3", ".", "0", "C")
        for index, label in enumerate(labels):
            button = QPushButton(label)
            button.setObjectName("key")
            button.clicked.connect(lambda _checked=False, value=label: self._press(value))
            if label == ".":
                self._dot = button
            keys.addWidget(button, index // 3, index % 3)
        self._dot.setEnabled(False)
        row.addLayout(keys)
        commands = QVBoxLayout()
        start = QPushButton("ПУСК")
        start.setObjectName("start")
        start.clicked.connect(self._start)
        stop = QPushButton("СТОП")
        stop.setObjectName("stop")
        stop.clicked.connect(self._stop)
        reset = QPushButton("Сброс дозы")
        reset.setObjectName("reset")
        reset.clicked.connect(self._reset)
        self.block_button = QPushButton("Блокировка пуска")
        self.block_button.setObjectName("block")
        self.block_button.clicked.connect(self._block)
        commands.addWidget(start)
        commands.addWidget(stop)
        commands.addWidget(reset)
        commands.addWidget(self.block_button)
        row.addLayout(commands)
        return deck

    def _build_training(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        note = QLabel("Звено эмулятора")
        row.addWidget(note)
        for title, slot, name in (
            ("Обрыв звена", self._cut, "cut-link"),
            ("Восстановить звено", self._restore, "restore-link"),
        ):
            button = QPushButton(title)
            button.setObjectName(name)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        return host

    def _login(self) -> None:
        try:
            self._service.login(self.login_name.text().strip(), self.login_password.text())
            try:
                shift = self._service.open_shift()
            except Exception as exc:  # noqa: BLE001
                if "уже открыта" not in str(exc):
                    raise
                self.shift.setText("Смена открыта")
            else:
                self.shift.setText(f"Смена {shift.number}")
        except Exception as exc:  # noqa: BLE001
            self._say(str(exc))
            return
        self._say("Смена открыта. Выберите колонку и наберите дозу.")
        self._tick()

    def _close_shift(self) -> None:
        try:
            shift = self._service.close_shift()
        except Exception as exc:  # noqa: BLE001
            self._say(str(exc))
            return
        self.shift.setText(f"Смена {shift.number} закрыта")
        self._say(f"Смена {shift.number} закрыта")

    def _tick(self) -> None:
        from datetime import datetime

        self.clock.setText(datetime.now().strftime("%H:%M:%S"))
        try:
            self._service.tick()
        except Exception as exc:  # noqa: BLE001
            self._say(str(exc))
            return
        if self._service.actor_id is not None:
            self._refresh()

    def _refresh(self) -> None:
        try:
            pumps = self._service.pumps()
        except Exception as exc:  # noqa: BLE001
            self._say(str(exc))
            return
        identifiers = [pump.pump_id for pump in pumps]
        if identifiers != self._order:
            self._rebuild(pumps)
        if self._selected not in self._faces and pumps:
            self._select(pumps[0].pump_id)
        for pump in pumps:
            self._addresses[pump.pump_id] = pump.address
            remembered = self._memory.get(pump.pump_id, (None, None))
            money, volume, remembered_ml, remembered_kzt = face_digits(
                status=pump.status,
                observation_quality=pump.observation_quality,
                dose_ml=pump.dose_ml,
                provisional_kzt=pump.provisional_kzt,
                remembered_ml=remembered[0],
                remembered_kzt=remembered[1],
            )
            self._memory[pump.pump_id] = (remembered_ml, remembered_kzt)
            chosen = pump.pump_id == self._selected
            self._faces[pump.pump_id].show_pump(pump, money, volume)
            self._faces[pump.pump_id].set_selected(chosen)
            self._switches[pump.pump_id].show_pump(pump, money, volume)
            self._switches[pump.pump_id].set_selected(chosen)
        self.block_button.setText(
            "Разрешить пуск" if self._service.commands_latched() else "Блокировка пуска"
        )

    def _rebuild(self, pumps: list[PumpView]) -> None:
        while self._rail.count():
            item = self._rail.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        while self._stage.count():
            widget = self._stage.widget(0)
            self._stage.removeWidget(widget)
            widget.deleteLater()
        self._faces.clear()
        self._switches.clear()
        self._order = [pump.pump_id for pump in pumps]
        for pump in pumps:
            switch = ColumnSwitch(pump.pump_id)
            switch.selected_callback = self._select
            face = ColumnFace(pump.pump_id)
            face.selected_callback = self._select
            self._switches[pump.pump_id] = switch
            self._faces[pump.pump_id] = face
            self._rail.addWidget(switch)
            self._stage.addWidget(face)
        current = self._faces.get(self._selected or "")
        if current is not None:
            self._stage.setCurrentWidget(current)

    def _select(self, pump_id: str) -> None:
        self._selected = pump_id
        for identifier, face in self._faces.items():
            face.set_selected(identifier == pump_id)
        for identifier, switch in self._switches.items():
            switch.set_selected(identifier == pump_id)
        current = self._faces.get(pump_id)
        if current is not None:
            self._stage.setCurrentWidget(current)
        self._show_buffer()

    def _selected_pump(self) -> PumpView | None:
        if self._selected is None:
            return None
        try:
            pumps = self._service.pumps()
        except Exception:  # noqa: BLE001
            return None
        for pump in pumps:
            if pump.pump_id == self._selected:
                return pump
        return None

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        self._buffer = ""
        self._dot.setEnabled(mode == "volume")
        self._show_buffer()

    def _press(self, key: str) -> None:
        if key == "C":
            self._buffer = ""
        elif key == ".":
            if self._mode != "volume" or "." in self._buffer:
                return
            self._buffer = (self._buffer or "0") + "."
        elif key.isdigit():
            if self._mode == "money" and len(self._buffer) >= 6:
                return
            if self._mode == "volume":
                frac = self._buffer.split(".")[1] if "." in self._buffer else ""
                if "." in self._buffer and len(frac) >= 2:
                    return
                if len(self._buffer) >= 7:
                    return
            self._buffer += key
        self._show_buffer()

    def _show_buffer(self) -> None:
        shown = self._buffer or "0"
        self.dose_entry.setText(shown)
        if self._mode == "money":
            self.dose_hint.setText("Режим: сумма, тенге")
            return
        pump = self._selected_pump()
        if pump is None or not self._buffer:
            self.dose_hint.setText("Режим: литры")
            return
        try:
            amount = preset_kzt(self._buffer, "volume", pump.price_kzt_per_liter)
        except ValueError:
            self.dose_hint.setText("Режим: литры")
            return
        self.dose_hint.setText(f"Режим: литры, к пуску {amount} тг")

    def _start(self) -> None:
        pump = self._selected_pump()
        if pump is None:
            self._say("Выберите колонку")
            return
        try:
            if self._service.commands_latched():
                raise RuntimeError("Пуск запрещён. Нажмите «Разрешить пуск», когда колонку снова можно открывать.")
            if pump.status == "READY" and pump.sale_id:
                sale = self._service.continue_dispense(pump.sale_id)
            elif pump.status == "PAYMENT_PENDING" and pump.sale_id and pump.payment_status == "CONFIRMED":
                sale = self._service.open_dispense_gate(pump.sale_id)
            else:
                amount = preset_kzt(self._buffer, self._mode, pump.price_kzt_per_liter)
                sale = self._service.begin_prepay(pump.pump_id, amount)
                sale = self._service.take_payment(sale.sale_id)
                sale = self._service.open_dispense_gate(sale.sale_id)
        except Exception as exc:  # noqa: BLE001
            self._say(str(exc))
            self._refresh()
            return
        self._memory.pop(pump.pump_id, None)
        self._say(f"Пуск. {sale.message}")
        self._refresh()

    def _stop(self) -> None:
        pump = self._selected_pump()
        if pump is None:
            self._say("Выберите колонку")
            return
        if pump.status != "DISPENSING":
            self._say("Колонка не в наливе. Клапан на оборудовании закрывается аппаратной кнопкой.")
            return
        if self._service.training:
            try:
                self._service.training_stop_early(pump.address)
            except Exception as exc:  # noqa: BLE001
                self._say(str(exc))
                return
            self._say("Налив на эмуляторе остановлен.")
            self._refresh()
            return
        self._block()

    def _reset(self) -> None:
        self._buffer = ""
        if self._selected is not None:
            self._memory.pop(self._selected, None)
        self._show_buffer()
        self._refresh()
        self._say("Доза сброшена.")

    def _block(self) -> None:
        try:
            if self._service.commands_latched():
                self._say(self._service.release_commands())
            else:
                self._say(self._service.latch_commands())
        except Exception as exc:  # noqa: BLE001
            self._say(str(exc))
            return
        self._refresh()

    def _history(self) -> None:
        self._open_log("events", show_event_journal)

    def _incidents(self) -> None:
        self._open_log("incidents", show_incidents)

    def _open_log(self, key: str, opener) -> None:
        current = self._logs.get(key)
        if current is not None and getattr(current, "isVisible", lambda: False)():
            current.raise_()
            current.activateWindow()
            current.reload()
            return
        try:
            dialog = opener(self, self._service)
        except Exception as exc:  # noqa: BLE001
            self._say(str(exc))
            return
        dialog.finished.connect(lambda _result: self._logs.pop(key, None))
        self._logs[key] = dialog

    def _cut(self) -> None:
        try:
            self._service.training_cut_link()
        except Exception as exc:  # noqa: BLE001
            self._say(str(exc))

    def _restore(self) -> None:
        try:
            self._service.training_restore_link()
        except Exception as exc:  # noqa: BLE001
            self._say(str(exc))

    def _say(self, text: str) -> None:
        self.message.setText(text)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if isinstance(self.focusWidget(), QLineEdit):
            super().keyPressEvent(event)
            return
        symbol = event.text()
        if symbol.isdigit() or symbol in ".,":
            self._press("." if symbol == "," else symbol)
            return
        if event.key() == Qt.Key.Key_Backspace:
            self._buffer = self._buffer[:-1]
            self._show_buffer()
            return
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self._start()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._press("C")
            return
        super().keyPressEvent(event)
