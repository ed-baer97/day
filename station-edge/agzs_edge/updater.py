"""Pull-автообновление станционного узла АГЗС: проверка SHA-256, простой, восстановление и авто-откат."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from agzs_edge import __version__
from agzs_edge.config import EdgeSettings, MAX_PUMP_ADDRESS
from agzs_edge.psu_controller import send_buttons_param_to_pumps
from agzs_edge.serial_link import build_link
from agzs_edge.storage import EdgeDatabase
from agzs_edge.sync import send_vps_request

logger = logging.getLogger(__name__)

_CURRENT_WHEEL_POINTER = "current_wheel.txt"
_UPDATE_STATE_FILENAME = "station_edge_update_state.json"


@dataclass(frozen=True)
class ReleaseManifest:
    """Манифест целевого релиза station-edge, полученный с центрального VPS."""

    version: str
    artifact_url: str
    sha256: str
    channel: str = "stable"
    min_version: str | None = None
    notes: str = ""
    signature: str | None = None
    update_required: bool = False


@dataclass(frozen=True)
class UpdateResult:
    """Итог запуска проверки или применения обновления на станции."""

    status: str  # up_to_date | update_available | updated | rolled_back | deferred_busy | failed
    current_version: str
    target_version: str
    message: str
    artifact_path: Path | None = None


@dataclass(frozen=True)
class UpdateProgressState:
    """Персистентное состояние процесса обновления (для /dev/tty1 и возобновления после сбоя питания)."""

    in_progress: bool
    phase: str  # downloading | waiting_idle | installing | restarting | recovering | completed | failed
    current_version: str
    target_version: str
    channel: str
    message: str
    artifact_url: str = ""
    sha256: str = ""
    min_version: str = ""
    signature: str = ""
    artifact_path: str = ""
    previous_wheel: str = ""
    interrupted_count: int = 0
    updated_at: str = ""
    buttons_locked: bool = False


def update_state_path(settings: EdgeSettings) -> Path:
    """Возвращает путь к файлу состояния обновления рядом с локальной БД."""
    return settings.db_path.parent / _UPDATE_STATE_FILENAME


def read_update_state(settings: EdgeSettings) -> UpdateProgressState | None:
    """Безопасно читает состояние обновления (в режиме только чтения без прав администратора)."""
    path = update_state_path(settings)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return UpdateProgressState(
            in_progress=bool(raw.get("in_progress", False)),
            phase=str(raw.get("phase") or ""),
            current_version=str(raw.get("current_version") or ""),
            target_version=str(raw.get("target_version") or ""),
            channel=str(raw.get("channel") or "stable"),
            message=str(raw.get("message") or ""),
            artifact_url=str(raw.get("artifact_url") or ""),
            sha256=str(raw.get("sha256") or ""),
            min_version=str(raw.get("min_version") or ""),
            signature=str(raw.get("signature") or ""),
            artifact_path=str(raw.get("artifact_path") or ""),
            previous_wheel=str(raw.get("previous_wheel") or ""),
            interrupted_count=int(raw.get("interrupted_count", 0) or 0),
            updated_at=str(raw.get("updated_at") or ""),
            buttons_locked=bool(raw.get("buttons_locked", False)),
        )
    except Exception:
        return None


def write_update_state(settings: EdgeSettings, state: UpdateProgressState) -> None:
    """Атомарно записывает состояние обновления на диск (переживает отключение питания)."""
    path = update_state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = (
        state
        if state.updated_at
        else UpdateProgressState(
            in_progress=state.in_progress,
            phase=state.phase,
            current_version=state.current_version,
            target_version=state.target_version,
            channel=state.channel,
            message=state.message,
            artifact_url=state.artifact_url,
            sha256=state.sha256,
            min_version=state.min_version,
            signature=state.signature,
            artifact_path=state.artifact_path,
            previous_wheel=state.previous_wheel,
            interrupted_count=state.interrupted_count,
            updated_at=datetime.now(timezone.utc).isoformat(),
            buttons_locked=state.buttons_locked,
        )
    )
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(asdict(stamped), ensure_ascii=False, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(tmp_path, 0o644)
    tmp_path.replace(path)


def clear_update_state(settings: EdgeSettings) -> None:
    """Снимает флаг активного обновления (возвращает монитор tty1 к обычному табло)."""
    with contextlib.suppress(OSError):
        update_state_path(settings).unlink(missing_ok=True)


def parse_version_tuple(version: str) -> tuple[int, ...]:
    """Разбирает строку версии ('0.2.1', 'v1.0.3') в кортеж целых чисел для сравнения."""
    cleaned = version.strip().lstrip("vV")
    if not cleaned:
        return (0,)
    parts: list[int] = []
    for token in cleaned.split("."):
        match = re.match(r"^(\d+)", token.strip())
        parts.append(int(match.group(1)) if match else 0)
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts) or (0,)


def is_newer_version(current: str, candidate: str) -> bool:
    """Возвращает True, если версия candidate новее current."""
    return parse_version_tuple(candidate) > parse_version_tuple(current)


def compute_sha256(file_path: Path) -> str:
    """Вычисляет SHA-256 хэш файла в hex (нижний регистр)."""
    digest = hashlib.sha256()
    with file_path.open("rb") as fh:
        while chunk := fh.read(65_536):
            digest.update(chunk)
    return digest.hexdigest().lower()


def verify_sha256(file_path: Path, expected_sha256: str) -> bool:
    """Проверяет соответствие SHA-256 файла ожидаемому хэшу."""
    expected = expected_sha256.strip().lower()
    if not expected or not file_path.is_file():
        return False
    return compute_sha256(file_path) == expected


def canonical_release_payload(version: str, sha256: str, min_version: str | None) -> bytes:
    """Каноническая строка для проверки HMAC-SHA256 подписи релиза station-edge."""
    return f"{version.strip()}\n{sha256.strip().lower()}\n{(min_version or '').strip()}".encode("utf-8")


def sign_release_manifest(
    version: str,
    sha256: str,
    min_version: str | None,
    signing_key: str,
) -> str:
    """Вычисляет HMAC-SHA256 (hex lowercase) для манифеста релиза station-edge."""
    return hmac.new(
        signing_key.strip().encode("utf-8"),
        canonical_release_payload(version, sha256, min_version),
        hashlib.sha256,
    ).hexdigest().lower()


def verify_release_signature(
    version: str,
    sha256: str,
    min_version: str | None,
    signature: str | None,
    signing_key: str,
) -> bool:
    """Проверяет HMAC-SHA256 подпись манифеста релиза (constant-time сравнение)."""
    sig = (signature or "").strip().lower()
    key = signing_key.strip()
    if not sig or not key:
        return False
    expected = sign_release_manifest(version, sha256, min_version, key)
    return hmac.compare_digest(sig, expected)


def fetch_release_manifest(
    vps_base_url: str,
    device_token: str,
    *,
    station_code: str,
    current_version: str,
    channel: str = "stable",
    outbox_pending: int = 0,
    timeout_sec: float = 10.0,
) -> ReleaseManifest:
    """Запрашивает манифест целевого релиза с центрального сервера."""
    query = urllib.parse.urlencode(
        {
            "channel": channel,
            "station_code": station_code,
            "current_version": current_version,
            "outbox_pending": str(max(0, outbox_pending)),
        }
    )
    res = send_vps_request(
        vps_base_url,
        f"/api/v1/ingest/edge/release?{query}",
        device_token,
        method="GET",
        timeout_sec=timeout_sec,
    )
    if not res.ok:
        raise RuntimeError(res.error_text or "Ошибка связи с VPS при проверке релиза")

    data = json.loads(res.response_text)
    artifact_url = str(data.get("artifact_url") or "")
    if artifact_url.startswith("/"):
        artifact_url = f"{vps_base_url.rstrip('/')}{artifact_url}"
    raw_sig = data.get("signature")
    return ReleaseManifest(
        version=str(data["version"]),
        artifact_url=artifact_url,
        sha256=str(data["sha256"]),
        channel=str(data.get("channel") or channel),
        min_version=data.get("min_version"),
        notes=str(data.get("notes") or ""),
        signature=str(raw_sig) if raw_sig is not None else None,
        update_required=bool(data.get("update_required", False)),
    )


def report_edge_heartbeat(
    vps_base_url: str,
    device_token: str,
    *,
    station_code: str,
    station_id: str,
    current_version: str,
    channel: str,
    outbox_pending: int,
    active_pumps: int,
    update_status: str,
    last_error: str | None = None,
    timeout_sec: float = 10.0,
) -> bool:
    """Отправляет на центральный VPS версию узла, очередь outbox и статус обновления."""
    payload = {
        "station_code": station_code,
        "station_id": station_id or None,
        "current_version": current_version,
        "channel": channel,
        "outbox_pending": max(0, int(outbox_pending)),
        "active_pumps": max(0, min(MAX_PUMP_ADDRESS, int(active_pumps))),
        "update_status": update_status,
        "last_error": last_error[:1024] if last_error else None,
    }
    res = send_vps_request(
        vps_base_url,
        "/api/v1/ingest/edge/heartbeat",
        device_token,
        method="POST",
        body_text=json.dumps(payload, ensure_ascii=False),
        timeout_sec=timeout_sec,
    )
    if not res.ok:
        logger.debug("Не удалось отправить heartbeat на VPS: %s", res.error_text)
    return res.ok


def download_release_artifact(
    artifact_url: str,
    dest_path: Path,
    *,
    device_token: str = "",
    timeout_sec: float = 60.0,
) -> Path:
    """Атомарно скачивает артефакт обновления (.whl) на диск станции."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")
    headers: dict[str, str] = {}
    if device_token:
        headers["X-Device-Token"] = device_token
    req = urllib.request.Request(url=artifact_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp, tmp_path.open("wb") as fh:
            while chunk := resp.read(65_536):
                fh.write(chunk)
        tmp_path.replace(dest_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return dest_path


def _default_installer(wheel_path: Path) -> None:
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--force-reinstall",
        str(wheel_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)


def _default_self_test() -> bool:
    cmd = [sys.executable, "-m", "agzs_edge", "--help"]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=15)
    return proc.returncode == 0


def _default_restart(restart_cmd: str) -> None:
    if not restart_cmd.strip():
        return
    parts = shlex.split(restart_cmd, posix=(os.name != "nt"))
    subprocess.run(parts, check=True, capture_output=True, text=True, timeout=30)


class EdgeUpdater:
    """Безопасный клиент Pull-обновления для сотен станционных серверов."""

    def __init__(
        self,
        settings: EdgeSettings,
        db: EdgeDatabase | None = None,
        *,
        current_version: str | None = None,
        manifest_fetcher: Callable[..., ReleaseManifest] | None = None,
        artifact_downloader: Callable[..., Path] | None = None,
        installer_fn: Callable[[Path], None] | None = None,
        self_test_fn: Callable[[], bool] | None = None,
        restart_fn: Callable[[str], None] | None = None,
        heartbeat_fn: Callable[..., bool] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        lock_pumps_fn: Callable[[], None] | None = None,
        unlock_pumps_fn: Callable[[], None] | None = None,
    ) -> None:
        self.settings = settings
        self.db = db or EdgeDatabase(settings.db_path, read_only=True)
        self.current_version = (current_version or __version__).strip() or __version__
        self._manifest_fetcher = manifest_fetcher or fetch_release_manifest
        self._artifact_downloader = artifact_downloader or download_release_artifact
        self._installer_fn = installer_fn or _default_installer
        self._self_test_fn = self_test_fn or _default_self_test
        self._restart_fn = restart_fn or _default_restart
        self._heartbeat_fn = heartbeat_fn or report_edge_heartbeat
        self._sleep_fn = sleep_fn or time.sleep
        self._lock_pumps_fn = lock_pumps_fn
        self._unlock_pumps_fn = unlock_pumps_fn

    def _safe_outbox_pending(self) -> int:
        try:
            info = self.db.summary()
            raw = info.get("outbox_pending", 0)
            return int(raw) if isinstance(raw, (int, float)) else 0
        except Exception:
            return 0

    def _safe_active_pumps(self) -> list[int]:
        try:
            return self.db.active_dispensing_pumps()
        except Exception:
            return []

    def _safe_idle_check(self, *, min_quiet_sec: float) -> tuple[bool, str]:
        try:
            return self.db.is_station_idle_for_update(min_quiet_sec=min_quiet_sec)
        except Exception:
            return True, "база недоступна"

    def _send_heartbeat(
        self,
        *,
        version: str,
        update_status: str,
        last_error: str | None = None,
    ) -> None:
        with contextlib.suppress(Exception):
            self._heartbeat_fn(
                self.settings.vps_base_url,
                self.settings.device_token,
                station_code=self.settings.station_code,
                station_id=self.settings.station_id,
                current_version=version,
                channel=self.settings.update_channel,
                outbox_pending=self._safe_outbox_pending(),
                active_pumps=len(self._safe_active_pumps()),
                update_status=update_status,
                last_error=last_error,
            )

    def _pointer_path(self) -> Path:
        return self.settings.releases_dir / _CURRENT_WHEEL_POINTER

    def _read_previous_wheel(self, *, fallback_path: str = "") -> Path | None:
        if fallback_path:
            fb = Path(fallback_path)
            if fb.is_file():
                return fb
        ptr = self._pointer_path()
        if not ptr.is_file():
            return None
        raw = ptr.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        candidate = Path(raw)
        return candidate if candidate.is_file() else None

    def _save_current_wheel(self, wheel_path: Path) -> None:
        ptr = self._pointer_path()
        ptr.parent.mkdir(parents=True, exist_ok=True)
        ptr.write_text(str(wheel_path), encoding="utf-8")

    def _send_buttons_param(self, param_code: str) -> bool:
        link = build_link(self.settings)
        try:
            _succeeded, errors = send_buttons_param_to_pumps(
                link,
                self.settings.pump_addresses,
                param_code,
                checksum_mode=self.settings.layout.tx_checksum_mode,
            )
            for address, err in errors:
                logger.debug("Колонка #%d: не удалось отправить %s (%s)", address, param_code, err)
            return not errors
        except Exception as exc:
            logger.debug("Ошибка прямого доступа к порту для команды %s: %s", param_code, exc)
            return False
        finally:
            with contextlib.suppress(Exception):
                link.close()

    def _signature_required(self) -> bool:
        return bool(self.settings.release_signing_key.strip() or self.settings.require_release_signature)

    def _has_valid_signature(
        self,
        *,
        version: str,
        sha256: str,
        min_version: str | None,
        signature: str | None,
    ) -> bool:
        if not self._signature_required():
            return True
        return verify_release_signature(
            version,
            sha256,
            min_version,
            signature,
            self.settings.release_signing_key,
        )

    def _write_progress(
        self,
        *,
        phase: str,
        target_version: str,
        channel: str,
        artifact_url: str = "",
        sha256: str = "",
        min_version: str = "",
        signature: str = "",
        artifact_path: str = "",
        previous_wheel: str = "",
        interrupted_count: int = 0,
        buttons_locked: bool = False,
    ) -> None:
        banner_msg = "ОБНОВЛЕНИЕ — КОЛОНКИ НЕДОСТУПНЫ"
        if interrupted_count > 0:
            banner_msg = "ОБНОВЛЕНИЕ — КОЛОНКИ НЕДОСТУПНЫ (возобновление после выключения питания)"
        write_update_state(
            self.settings,
            UpdateProgressState(
                in_progress=True,
                phase=phase,
                current_version=self.current_version,
                target_version=target_version,
                channel=channel,
                message=banner_msg,
                artifact_url=artifact_url,
                sha256=sha256,
                min_version=min_version,
                signature=signature,
                artifact_path=artifact_path,
                previous_wheel=previous_wheel,
                interrupted_count=interrupted_count,
                buttons_locked=buttons_locked,
            ),
        )

    def _cleanup_interrupted(self, interrupted: bool) -> None:
        if interrupted:
            clear_update_state(self.settings)
            self._unlock_pumps_after_install()

    def _fail_update(
        self,
        err: str,
        *,
        target_version: str | None = None,
        clear_interrupted: bool = False,
    ) -> UpdateResult:
        self._cleanup_interrupted(clear_interrupted)
        self._send_heartbeat(
            version=self.current_version,
            update_status="failed",
            last_error=err,
        )
        return UpdateResult(
            status="failed",
            current_version=self.current_version,
            target_version=target_version or self.current_version,
            message=err,
        )

    def _lock_pumps_before_install(self) -> None:
        if self._lock_pumps_fn is not None:
            try:
                self._lock_pumps_fn()
            except Exception as exc:
                logger.warning("Ошибка блокировки кнопок колонок перед обновлением: %s", exc)
            return
        if self.settings.read_only or not self.settings.lock_buttons_on_update:
            return
        if not self._send_buttons_param("0.17"):
            # Порт занят работающим station-edge.service: ждём подтверждения buttons_locked от службы.
            wait_budget = max(3.0, self.settings.poll_interval_sec * 4 + self.settings.serial_timeout_sec)
            deadline = time.monotonic() + wait_budget
            while time.monotonic() < deadline:
                state = read_update_state(self.settings)
                if state is not None and state.buttons_locked:
                    return
                self._sleep_fn(0.2)

    def _unlock_pumps_after_install(self) -> None:
        if self._unlock_pumps_fn is not None:
            try:
                self._unlock_pumps_fn()
            except Exception as exc:
                logger.warning("Ошибка включения кнопок колонок после обновления: %s", exc)
            return
        if self.settings.read_only or not self.settings.lock_buttons_on_update:
            return
        param_code = "0.16"
        with contextlib.suppress(Exception):
            self._send_buttons_param(param_code)

    def wait_until_idle(
        self,
        *,
        timeout_sec: float = 180.0,
        min_quiet_sec: float | None = None,
        poll_sec: float = 1.0,
    ) -> tuple[bool, str]:
        """Ждёт наступления простоя станции перед установкой и рестартом службы."""
        effective_quiet = (
            self.settings.update_idle_quiet_sec if min_quiet_sec is None else max(0.0, min_quiet_sec)
        )
        idle, reason = self._safe_idle_check(min_quiet_sec=effective_quiet)
        if idle:
            return True, reason
        if timeout_sec <= 0:
            return False, reason

        deadline = time.monotonic() + timeout_sec
        step = max(0.05, poll_sec)
        while not idle:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False, reason
            self._sleep_fn(min(step, remaining))
            idle, reason = self._safe_idle_check(min_quiet_sec=effective_quiet)
        return True, reason

    def _rollback(self, previous_wheel: Path | None, restart_cmd: str, error_msg: str) -> UpdateResult:
        if previous_wheel is None:
            return self._fail_update(
                f"Обновление не удалось (предыдущий .whl для отката отсутствует): {error_msg}",
                clear_interrupted=True,
            )

        try:
            self._installer_fn(previous_wheel)
            if restart_cmd.strip():
                self._restart_fn(restart_cmd)
        except Exception as rb_exc:
            return self._fail_update(
                f"{error_msg}; ошибка отката: {rb_exc}",
                clear_interrupted=True,
            )

        self._cleanup_interrupted(True)
        self._send_heartbeat(
            version=self.current_version,
            update_status="rolled_back",
            last_error=error_msg,
        )
        return UpdateResult(
            status="rolled_back",
            current_version=self.current_version,
            target_version=self.current_version,
            message=f"Выполнен авто-откат на {previous_wheel.name} после сбоя: {error_msg}",
            artifact_path=previous_wheel,
        )

    def _apply_verified_wheel(
        self,
        *,
        wheel_path: Path,
        target_version: str,
        channel: str,
        artifact_url: str,
        sha256: str,
        min_version: str = "",
        signature: str = "",
        previous_wheel: Path | None,
        restart_cmd: str,
        interrupted_count: int = 0,
    ) -> UpdateResult:
        """Устанавливает проверенный .whl, фиксирует состояние для /dev/tty1 и снимает блокировку по итогам."""
        prev_str = str(previous_wheel) if previous_wheel else ""
        self._write_progress(
            phase="installing",
            target_version=target_version,
            channel=channel,
            artifact_url=artifact_url,
            sha256=sha256,
            min_version=min_version,
            signature=signature,
            artifact_path=str(wheel_path),
            previous_wheel=prev_str,
            interrupted_count=interrupted_count,
        )
        self._lock_pumps_before_install()
        try:
            self._installer_fn(wheel_path)
            if not self._self_test_fn():
                raise RuntimeError("smoke-тест `python -m agzs_edge --help` завершился с ошибкой")
            if restart_cmd.strip():
                cur_state = read_update_state(self.settings)
                self._write_progress(
                    phase="restarting",
                    target_version=target_version,
                    channel=channel,
                    artifact_url=artifact_url,
                    sha256=sha256,
                    min_version=min_version,
                    signature=signature,
                    artifact_path=str(wheel_path),
                    previous_wheel=prev_str,
                    interrupted_count=interrupted_count,
                    buttons_locked=bool(cur_state.buttons_locked) if cur_state else False,
                )
                self._restart_fn(restart_cmd)
        except Exception as exc:
            return self._rollback(previous_wheel, restart_cmd, str(exc))

        self._save_current_wheel(wheel_path)
        self._cleanup_interrupted(True)
        self._send_heartbeat(
            version=target_version,
            update_status="updated",
        )
        return UpdateResult(
            status="updated",
            current_version=self.current_version,
            target_version=target_version,
            message=f"Станция успешно обновлена: {self.current_version} -> {target_version}",
            artifact_path=wheel_path,
        )

    def _resume_interrupted_update(
        self,
        prev_state: UpdateProgressState,
        *,
        wait_idle_sec: float,
        min_quiet_sec: float | None,
        restart_cmd: str,
    ) -> UpdateResult | None:
        """Пытается автоматически завершить обновление, прерванное выключением питания."""
        next_interrupted = prev_state.interrupted_count + 1
        logger.warning(
            "Обнаружено прерванное обновление (%s -> %s, фаза=%s, сбоев=%d): возобновляем...",
            prev_state.current_version,
            prev_state.target_version,
            prev_state.phase,
            next_interrupted,
        )
        self._write_progress(
            phase="recovering",
            target_version=prev_state.target_version,
            channel=prev_state.channel or self.settings.update_channel,
            artifact_url=prev_state.artifact_url,
            sha256=prev_state.sha256,
            min_version=prev_state.min_version,
            signature=prev_state.signature,
            artifact_path=prev_state.artifact_path,
            previous_wheel=prev_state.previous_wheel,
            interrupted_count=next_interrupted,
        )

        local_pkg = Path(prev_state.artifact_path) if prev_state.artifact_path else None
        prev_wheel = self._read_previous_wheel(fallback_path=prev_state.previous_wheel)

        if local_pkg is not None and prev_state.sha256 and verify_sha256(local_pkg, prev_state.sha256):
            if not self._has_valid_signature(
                version=prev_state.target_version,
                sha256=prev_state.sha256,
                min_version=prev_state.min_version or None,
                signature=prev_state.signature or None,
            ):
                local_pkg.unlink(missing_ok=True)
                return self._fail_update(
                    "Недействительная или отсутствует подпись релиза (HMAC-SHA256)",
                    target_version=prev_state.target_version,
                    clear_interrupted=True,
                )

            if prev_state.target_version and not is_newer_version(
                self.current_version, prev_state.target_version
            ):
                self._save_current_wheel(local_pkg)
                self._cleanup_interrupted(True)
                self._send_heartbeat(version=self.current_version, update_status="updated")
                return UpdateResult(
                    status="updated",
                    current_version=self.current_version,
                    target_version=prev_state.target_version,
                    message=f"Возобновлено после перезагрузки: версия {self.current_version} уже активна",
                    artifact_path=local_pkg,
                )

            idle_ok, busy_reason = self.wait_until_idle(
                timeout_sec=wait_idle_sec,
                min_quiet_sec=min_quiet_sec,
            )
            if not idle_ok:
                self._cleanup_interrupted(True)
                msg = f"Возобновление обновления отложено: {busy_reason}"
                self._send_heartbeat(
                    version=self.current_version,
                    update_status="deferred_busy",
                    last_error=msg,
                )
                return UpdateResult(
                    status="deferred_busy",
                    current_version=self.current_version,
                    target_version=prev_state.target_version,
                    message=msg,
                    artifact_path=local_pkg,
                )

            return self._apply_verified_wheel(
                wheel_path=local_pkg,
                target_version=prev_state.target_version,
                channel=prev_state.channel or self.settings.update_channel,
                artifact_url=prev_state.artifact_url,
                sha256=prev_state.sha256,
                min_version=prev_state.min_version,
                signature=prev_state.signature,
                previous_wheel=prev_wheel,
                restart_cmd=restart_cmd,
                interrupted_count=next_interrupted,
            )

        if local_pkg is not None:
            local_pkg.unlink(missing_ok=True)
        return None

    def run_update(
        self,
        *,
        check_only: bool = False,
        wait_idle_sec: float = 180.0,
        min_quiet_sec: float | None = None,
        restart_cmd: str = "",
    ) -> UpdateResult:
        """Проверяет релиз на VPS и безопасно обновляет станционный узел (во время простоя, с авто-откатом)."""
        interrupted_state: UpdateProgressState | None = None
        if not check_only:
            prev_state = read_update_state(self.settings)
            if prev_state is not None and prev_state.in_progress:
                resumed = self._resume_interrupted_update(
                    prev_state,
                    wait_idle_sec=wait_idle_sec,
                    min_quiet_sec=min_quiet_sec,
                    restart_cmd=restart_cmd,
                )
                if resumed is not None:
                    return resumed
                interrupted_state = prev_state

        outbox_pending = self._safe_outbox_pending()
        has_interrupted = interrupted_state is not None
        try:
            manifest = self._manifest_fetcher(
                self.settings.vps_base_url,
                self.settings.device_token,
                station_code=self.settings.station_code,
                current_version=self.current_version,
                channel=self.settings.update_channel,
                outbox_pending=outbox_pending,
            )
        except Exception as exc:
            err = str(exc)
            if interrupted_state is not None:
                prev_wheel = self._read_previous_wheel(fallback_path=interrupted_state.previous_wheel)
                if prev_wheel is not None:
                    return self._rollback(
                        prev_wheel,
                        restart_cmd,
                        f"нет связи с VPS при возобновлении после сбоя питания: {err}",
                    )
            return self._fail_update(err, clear_interrupted=has_interrupted)

        if not is_newer_version(self.current_version, manifest.version):
            self._cleanup_interrupted(has_interrupted)
            self._send_heartbeat(
                version=self.current_version,
                update_status="up_to_date",
            )
            return UpdateResult(
                status="up_to_date",
                current_version=self.current_version,
                target_version=manifest.version,
                message=f"Установлена актуальная версия {self.current_version} (целевая {manifest.version})",
            )

        if manifest.min_version and parse_version_tuple(self.current_version) < parse_version_tuple(
            manifest.min_version
        ):
            return self._fail_update(
                f"Требуется промежуточное обновление: текущая {self.current_version} < min_version {manifest.min_version}",
                target_version=manifest.version,
                clear_interrupted=has_interrupted,
            )

        if not self._has_valid_signature(
            version=manifest.version,
            sha256=manifest.sha256,
            min_version=manifest.min_version,
            signature=manifest.signature,
        ):
            return self._fail_update(
                "Недействительная или отсутствует подпись релиза (HMAC-SHA256)",
                target_version=manifest.version,
                clear_interrupted=has_interrupted,
            )

        if check_only:
            return UpdateResult(
                status="update_available",
                current_version=self.current_version,
                target_version=manifest.version,
                message=f"Доступна новая версия {manifest.version} (канал {manifest.channel})",
            )

        artifact_path = self.settings.releases_dir / f"agzs_edge-{manifest.version}.whl"
        try:
            downloaded_path = self._artifact_downloader(
                manifest.artifact_url,
                artifact_path,
                device_token=self.settings.device_token,
            )
        except Exception as exc:
            return self._fail_update(
                f"Не удалось скачать артефакт {manifest.version}: {exc}",
                target_version=manifest.version,
                clear_interrupted=has_interrupted,
            )

        if not verify_sha256(downloaded_path, manifest.sha256):
            downloaded_path.unlink(missing_ok=True)
            return self._fail_update(
                f"Ошибка контрольной суммы SHA-256 для {downloaded_path.name}",
                target_version=manifest.version,
                clear_interrupted=has_interrupted,
            )

        idle_ok, busy_reason = self.wait_until_idle(
            timeout_sec=wait_idle_sec,
            min_quiet_sec=min_quiet_sec,
        )
        if not idle_ok:
            self._cleanup_interrupted(has_interrupted)
            msg = f"Обновление до {manifest.version} отложено (ждём простой станции): {busy_reason}"
            self._send_heartbeat(
                version=self.current_version,
                update_status="deferred_busy",
                last_error=msg,
            )
            return UpdateResult(
                status="deferred_busy",
                current_version=self.current_version,
                target_version=manifest.version,
                message=msg,
                artifact_path=downloaded_path,
            )

        previous_wheel = self._read_previous_wheel(
            fallback_path=interrupted_state.previous_wheel if interrupted_state else ""
        )
        interrupted_count = (interrupted_state.interrupted_count + 1) if interrupted_state else 0
        return self._apply_verified_wheel(
            wheel_path=downloaded_path,
            target_version=manifest.version,
            channel=manifest.channel,
            artifact_url=manifest.artifact_url,
            sha256=manifest.sha256,
            min_version=manifest.min_version or "",
            signature=manifest.signature or "",
            previous_wheel=previous_wheel,
            restart_cmd=restart_cmd,
            interrupted_count=interrupted_count,
        )
