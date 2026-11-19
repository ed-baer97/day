import { useEffect } from "react";

export default function ConfirmModal({
  open,
  title,
  message,
  details,
  confirmLabel = "Подтвердить",
  cancelLabel = "Отмена",
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  details?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onCancel]);

  if (!open) return null;

  return (
    <div
      className="login-layer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
      onClick={() => {
        if (!busy) onCancel();
      }}
    >
      <div className="login-card confirm-modal" onClick={(event) => event.stopPropagation()}>
        <h2 id="confirm-modal-title">{title}</h2>
        <p style={{ margin: "6px 0 0" }}>{message}</p>
        {details ? (
          <p className="dash-muted" style={{ marginTop: 8 }}>
            {details}
          </p>
        ) : null}
        <div className="login-actions" style={{ marginTop: 18 }}>
          <button
            type="button"
            className="btn secondary"
            disabled={busy}
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`btn${danger ? " btn-danger" : ""}`}
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? "Выполняем…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
