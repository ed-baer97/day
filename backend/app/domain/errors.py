"""Доменные исключения. Преобразуются в HTTP-ответ единым обработчиком в main.py."""

from __future__ import annotations


class DomainError(Exception):
    """Базовая доменная ошибка без зависимости от FastAPI."""

    status_code: int = 400

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(DomainError):
    status_code = 404


class ConflictError(DomainError):
    status_code = 409


class ValidationError(DomainError):
    status_code = 422


class ForbiddenError(DomainError):
    status_code = 403


class CalibrationRequired(ValidationError):
    """Для volts нужна калибровка резервуара."""
