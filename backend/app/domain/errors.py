"""Ошибки домена. HTTP-код им назначает порт учёта, не книга резервуара."""


class CalibrationRequired(Exception):
    """Для volts нужна калибровка резервуара."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail
