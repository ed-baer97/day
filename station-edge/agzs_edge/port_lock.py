"""Межпроцессная эксклюзивная блокировка последовательного порта АСКА-02."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import TextIO


class PortBusyError(RuntimeError):
    """Порт RS-232 уже открыт другим процессом station-edge."""


def _lock_file_for_port(port: str, lock_dir: Path | None) -> Path:
    base_dir = lock_dir if lock_dir is not None else Path(tempfile.gettempdir())
    normalized = port.strip().lower()
    slug = re.sub(r"[^a-z0-9._-]+", "_", normalized).strip("_") or "port"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    return base_dir / f"agzs_port_{slug}_{digest}.lock"


class ExclusivePortLock:
    """Неблокирующая межпроцессная блокировка доступа к одному COM/TTY-порту."""

    def __init__(self, port: str, *, lock_dir: Path | None = None) -> None:
        self.port = port
        self.lock_path = _lock_file_for_port(port, lock_dir)
        self._fh: TextIO | None = None

    def acquire(self) -> None:
        if self._fh is not None:
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = self.lock_path.open("a+", encoding="utf-8")
        try:
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                fh.write(" ")
                fh.flush()
            fh.seek(0)
            if os.name == "posix":
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            self._fh = fh
        except OSError as exc:
            with contextlib.suppress(Exception):
                fh.close()
            raise PortBusyError(
                f"Порт {self.port} занят другим процессом station-edge "
                "(остановите службу station-edge перед ручной командой)"
            ) from exc

    def release(self) -> None:
        fh = self._fh
        if fh is None:
            return
        self._fh = None
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            else:
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            with contextlib.suppress(Exception):
                fh.close()

    def __enter__(self) -> "ExclusivePortLock":
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()
