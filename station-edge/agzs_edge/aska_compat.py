"""Observe the CURRENT driver's I/O. No port opening, protocol or extra polling.

Use within the existing port lock, one Attempt per existing transaction.
write()/read() each invoke the supplied existing operation exactly once and
return its original result or re-raise its original exception. Diagnostics stay
in memory until report() is called; journal/file writes belong outside timing.
"""
from __future__ import annotations

import hashlib
import time
from typing import Callable, Any


class Attempt:
    def __init__(self, expected_tx: bytes, *, channel: int, capture_limit: int = 4096,
                 event_limit: int = 128):
        if not isinstance(expected_tx, bytes) or not expected_tx:
            raise ValueError("expected_tx must be the existing nonempty bytes frame")
        if not isinstance(channel, int) or channel < 1:
            raise ValueError("channel must be the actual positive channel number")
        if capture_limit < 0 or event_limit < 0:
            raise ValueError("limits must be nonnegative")
        self.expected_tx = expected_tx
        self.channel = channel
        self.capture_limit, self.event_limit = capture_limit, event_limit
        self.started_ns = time.monotonic_ns()
        self.events: list[dict] = []
        self.events_dropped = 0
        self.captured = 0
        self.tx_accepted = self.tx_calls = self.rx_calls = self.rx_bytes = self.rx_zero_bytes = 0
        self.tx_matches = True
        self.tx_return_unknown = False
        self.read_type_error = False
        self.tx_exception: str | None = None
        self.rx_exception: str | None = None
        self.tx_digest, self.rx_digest = hashlib.sha256(), hashlib.sha256()
        self.decoded = self.rejected_frames = self.unmatched_frames = 0
        self.value: Any = None
        self.remote_error: str | None = None

    def _event(self, kind: str, data: bytes | None = None, **fields) -> None:
        if len(self.events) >= self.event_limit:
            self.events_dropped += 1
            return
        event = {"offset_ns": time.monotonic_ns() - self.started_ns, "kind": kind, **fields}
        if data is not None:
            room = max(0, self.capture_limit - self.captured)
            fragment = data[:room]
            self.captured += len(fragment)
            event.update(length=len(data), hex=fragment.hex(" "), truncated=len(fragment) < len(data))
        self.events.append(event)

    def write(self, original_write: Callable, data, *args, **kwargs):
        """No completion loop: preserve even the old driver's partial-write behaviour."""
        self.tx_calls += 1
        snapshot = bytes(data) if isinstance(data, (bytes, bytearray, memoryview)) else None
        try:
            result = original_write(data, *args, **kwargs)
        except Exception as error:
            self.tx_exception = type(error).__name__
            self._event("TX_EXCEPTION", exception_type=self.tx_exception)
            raise
        if snapshot is None:
            self.tx_return_unknown = True
            self._event("TX_UNOBSERVABLE_TYPE", data_type=type(data).__name__)
            return result
        if isinstance(result, int) and not isinstance(result, bool) and 0 <= result <= len(snapshot):
            accepted = snapshot[:result]
            start = self.tx_accepted
            self.tx_accepted += result
            if self.tx_accepted > len(self.expected_tx) or accepted != self.expected_tx[start:self.tx_accepted]:
                self.tx_matches = False
            self.tx_digest.update(accepted)
            self._event("TX_RETURN", snapshot, accepted=result)
        else:
            self.tx_return_unknown = True
            self._event("TX_UNKNOWN_RETURN", snapshot, return_type=type(result).__name__)
        return result

    def read(self, original_read: Callable, *args, **kwargs):
        self.rx_calls += 1
        try:
            result = original_read(*args, **kwargs)
        except Exception as error:
            self.rx_exception = type(error).__name__
            self._event("RX_EXCEPTION", exception_type=self.rx_exception)
            raise
        if isinstance(result, (bytes, bytearray, memoryview)):
            data = bytes(result)
            self.rx_bytes += len(data)
            self.rx_zero_bytes += data.count(0)
            self.rx_digest.update(data)
            self._event("RX_RETURN", data)
        else:
            self.read_type_error = True
            self._event("RX_UNOBSERVABLE_TYPE", return_type=type(result).__name__)
        return result

    def parser_result(self, *, frame_valid: bool, matches_request: bool,
                      value: Any = None, remote_error: str | None = None) -> None:
        """Called by the EXISTING documented parser, never by a guessed decoder.

        Flags are the caller's observations, not validation performed here.
        `value=0` is preserved when a valid matched reply exists.
        """
        if type(frame_valid) is not bool or type(matches_request) is not bool:
            raise ValueError("parser flags must be explicit booleans")
        if not frame_valid:
            self.rejected_frames += 1
            self._event("PARSER_REJECTED")
            return
        if not matches_request:
            self.unmatched_frames += 1
            self._event("PARSER_UNMATCHED")
            return
        self.decoded += 1
        self.value, self.remote_error = value, remote_error
        self._event("PARSER_ACCEPTED", has_value=value is not None, remote_error=remote_error)

    def report(self, *, driver_reported_timeout: bool = False) -> dict:
        """Snapshot only. This method never changes application state or values."""
        if self.tx_exception:
            code = "TX_EXCEPTION"
        elif self.rx_exception:
            code = "RX_EXCEPTION"
        elif self.tx_return_unknown:
            code = "TX_RESULT_UNKNOWN"
        elif not self.tx_matches:
            code = "TX_DIFFERS_FROM_EXISTING_FRAME"
        elif self.tx_accepted != len(self.expected_tx):
            code = "TX_INCOMPLETE"
        elif self.read_type_error:
            code = "RX_TYPE_UNKNOWN"
        elif self.rx_calls == 0:
            code = "READ_NOT_CALLED"
        elif self.rx_bytes == 0:
            code = "RX_ZERO_AT_DRIVER_TIMEOUT" if driver_reported_timeout else "RX_ZERO_AT_OBSERVATION_END"
        elif not self.decoded:
            code = "RX_REJECTED_BY_EXISTING_PARSER" if self.rejected_frames else "RX_UNMATCHED" if self.unmatched_frames else "RX_NOT_VALIDATED"
        elif self.remote_error is not None:
            code = "DEVICE_REPORTED_ERROR"
        elif driver_reported_timeout:
            code = "DRIVER_TIMEOUT_DESPITE_PARSED_REPLY"
        else:
            code = "VALID_REPLY_REPORTED_BY_EXISTING_PARSER"
        success = code == "VALID_REPLY_REPORTED_BY_EXISTING_PARSER"
        return {
            "schema": "aska-current-io-evidence/1", "channel": self.channel,
            "code": code, "elapsed_ms": (time.monotonic_ns() - self.started_ns) / 1_000_000,
            "tx_calls": self.tx_calls, "tx_expected_length": len(self.expected_tx),
            "tx_accepted_by_driver": self.tx_accepted,
            "tx_exactly_matches_existing_frame": bool(self.tx_matches and not self.tx_return_unknown and not self.tx_exception and self.tx_accepted == len(self.expected_tx)),
            "tx_sha256": self.tx_digest.hexdigest(), "rx_calls": self.rx_calls,
            "rx_bytes": self.rx_bytes, "rx_zero_bytes": self.rx_zero_bytes,
            "rx_sha256": self.rx_digest.hexdigest(), "rejected_frames": self.rejected_frames,
            "unmatched_frames": self.unmatched_frames, "accepted_frames": self.decoded,
            "driver_reported_timeout": driver_reported_timeout,
            "measurement_valid": bool(success and self.value is not None),
            "value": self.value if success else None, "device_error": self.remote_error,
            "exception_types": {"write": self.tx_exception, "read": self.rx_exception},
            "events_dropped": self.events_dropped,
            "trace_truncated": bool(self.events_dropped or any(e.get("truncated") for e in self.events)),
            "events": list(self.events),
            "physical_fault": None,
        }


def compare_tx(baseline: bytes, candidate: bytes, expected_length: int | None = None) -> dict:
    """Byte-for-byte regression test, NOT proof that a device accepts either frame."""
    same = baseline == candidate
    length_ok = expected_length is None or len(baseline) == len(candidate) == expected_length
    return {
        "same_bytes": same, "length_check_passed": length_ok,
        "baseline_length": len(baseline), "candidate_length": len(candidate),
        "expected_length": expected_length,
        "baseline_sha256": hashlib.sha256(baseline).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "different_offsets": [i for i in range(max(len(baseline), len(candidate)))
                              if baseline[i:i+1] != candidate[i:i+1]],
        "wire_format_preserved": same and length_ok,
        "device_acceptance_confirmed": False,
    }
