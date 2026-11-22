import { useEffect, useRef, useState } from "react";
import { isAdmin } from "../access";
import {
  api,
  type AdminTankOverview,
  type ShellyLink,
  type TankDevice,
  type TankIngestState,
} from "../api/client";
import { useAuth } from "../auth";
import { useCatalog } from "../catalog";
import { messageOf } from "../errors";
import { liters } from "../format";
import { tankSensorBadge, tankSensorLabel, usePublicLevels } from "../liveLevels";
import ConfirmModal from "./ConfirmModal";
import { useToast } from "./Toast";

type Row = {
  id: string;
  code: string;
  capacity: string;
  token: string;
  path: string;
  shellyHost: string;
  shelly: ShellyLink | null;
  lowVolts: string;
  lowPercent: string;
  highVolts: string;
  highPercent: string;
  calibrated: boolean;
  calSummary: string | null;
  manualLiters: string;
  receiptLiters: string;
  actualLiters: number | null;
  online: boolean;
};

function ingestUrl(path: string) {
  if (path.startsWith("http")) return path;
  return `${window.location.origin}${path}`;
}

export default function TankDeviceRows({
  stationId,
  initialStates,
  onChanged,
}: {
  stationId: string;
  initialStates?: AdminTankOverview[];
  onChanged?: () => void;
}) {
  const { session } = useAuth();
  const canManage = isAdmin(session);
  const { byCode } = usePublicLevels();
  const toast = useToast();
  const [rows, setRows] = useState<Row[]>([]);
  const [code, setCode] = useState("");
  const [capacity, setCapacity] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [expandedToolsId, setExpandedToolsId] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<
    | { kind: "delete"; row: Row }
    | { kind: "rotate"; row: Row }
    | null
  >(null);
  const shellyFresh = useRef<Record<string, number>>({});
  const overviewMapRef = useRef<Map<string, AdminTankOverview>>(new Map());

  const catalog = useCatalog();
  const stationCode = catalog.stations.find((row) => row.id === stationId)?.code;
  const live = stationCode ? byCode.get(stationCode) : undefined;

  useEffect(() => {
    const map = new Map<string, AdminTankOverview>();
    for (const item of initialStates ?? []) map.set(item.id, item);
    overviewMapRef.current = map;
  }, [initialStates]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    api
      .tankDevices(stationId)
      .then(async (devices) => {
        if (!alive) return;
        const states = await Promise.all(
          devices.map(async (device) => {
            const ov = overviewMapRef.current.get(device.id);
            if (ov) return [device.id, ov] as const;
            try {
              const st = await api.tankIngestState(device.id);
              return [device.id, st] as const;
            } catch {
              return [device.id, null] as const;
            }
          })
        );
        if (!alive) return;
        const stateById = new Map<string, AdminTankOverview | TankIngestState | null>(states);
        setRows(devices.map((device) => toRow(device, stateById.get(device.id) ?? null)));
      })
      .catch((err) => {
        if (!alive) return;
        setRows([]);
        setError(messageOf(err, "Не удалось загрузить резервуары"));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [stationId]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const started = Date.now();
      api
        .tankDevices(stationId)
        .then((devices) => {
          const byId = new Map(devices.map((device) => [device.id, device.shelly]));
          setRows((current) =>
            current.map((row) => {
              if (!byId.has(row.id)) return row;
              if ((shellyFresh.current[row.id] ?? 0) >= started) return row;
              return { ...row, shelly: byId.get(row.id) ?? null };
            })
          );
        })
        .catch(() => undefined);
    }, 8000);
    return () => window.clearInterval(timer);
  }, [stationId]);

  async function addTank() {
    const volume = Number(capacity.replace(",", "."));
    if (!code.trim() || !Number.isFinite(volume) || volume <= 0) {
      setError("Укажите код и объём в литрах");
      return;
    }
    setSavingId("new");
    setError(null);
    try {
      const created = await api.createTankDevice(stationId, {
        code: code.trim(),
        capacity_liters: volume,
      });
      setRows((current) => [...current, toRow(created, null)]);
      setCode("");
      setCapacity("");
      toast.ok(`Резервуар ${created.code} добавлен`);
      onChanged?.();
    } catch (err) {
      setError(messageOf(err, "Не удалось сохранить"));
    } finally {
      setSavingId(null);
    }
  }

  async function saveRow(row: Row) {
    const volume = Number(row.capacity.replace(",", "."));
    if (!row.code.trim() || !Number.isFinite(volume) || volume <= 0) {
      setError("Укажите код и объём в литрах");
      return;
    }
    setSavingId(row.id);
    setError(null);
    try {
      const updated = await api.updateTankDevice(stationId, row.id, {
        code: row.code.trim(),
        capacity_liters: volume,
      });
      setRows((current) =>
        current.map((item) =>
          item.id === row.id
            ? {
                ...item,
                code: updated.code,
                capacity: String(updated.capacity_liters),
                shelly: updated.shelly,
              }
            : item
        )
      );
      toast.ok(`Резервуар ${row.code} сохранён`);
      onChanged?.();
    } catch (err) {
      setError(messageOf(err, "Не удалось сохранить"));
    } finally {
      setSavingId(null);
    }
  }

  async function confirmPendingAction() {
    if (!pendingAction) return;
    const { kind, row } = pendingAction;
    if (kind === "delete") {
      setSavingId(`del:${row.id}`);
      setError(null);
      try {
        await api.deleteTankDevice(stationId, row.id);
        setRows((current) => current.filter((item) => item.id !== row.id));
        setPendingAction(null);
        toast.ok(`Резервуар ${row.code} удалён`);
        onChanged?.();
      } catch (err) {
        setError(messageOf(err, "Не удалось удалить резервуар"));
      } finally {
        setSavingId(null);
      }
      return;
    }

    setSavingId(`rot:${row.id}`);
    setError(null);
    try {
      const updated = await api.rotateTankToken(stationId, row.id);
      setRows((current) =>
        current.map((item) =>
          item.id === row.id ? { ...item, token: updated.ingest_token ?? "" } : item
        )
      );
      setPendingAction(null);
      toast.ok(`Токен резервуара ${row.code} перевыпущен`);
      onChanged?.();
    } catch (err) {
      setError(messageOf(err, "Не удалось перевыпустить токен"));
    } finally {
      setSavingId(null);
    }
  }

  async function connectShelly(row: Row) {
    const host = row.shellyHost.trim();
    if (!host) {
      setError("Укажите IP Shelly");
      return;
    }
    setSavingId(`shelly:${row.id}`);
    setError(null);
    try {
      const updated = await api.connectShelly(stationId, row.id, host);
      shellyFresh.current[row.id] = Date.now();
      setRows((current) =>
        current.map((item) =>
          item.id === row.id
            ? { ...item, shelly: updated.shelly, shellyHost: updated.shelly?.host ?? host }
            : item
        )
      );
      onChanged?.();
    } catch (err) {
      setError(messageOf(err, "Не удалось подключить Shelly"));
    } finally {
      setSavingId(null);
    }
  }

  async function disconnectShelly(row: Row) {
    setSavingId(`shelly:${row.id}`);
    setError(null);
    try {
      const updated = await api.disconnectShelly(stationId, row.id);
      shellyFresh.current[row.id] = Date.now();
      setRows((current) =>
        current.map((item) =>
          item.id === row.id
            ? { ...item, shelly: updated.shelly }
            : item
        )
      );
      onChanged?.();
    } catch (err) {
      setError(messageOf(err, "Не удалось отключить Shelly"));
    } finally {
      setSavingId(null);
    }
  }

  async function submitCalibration(row: Row) {
    const lowV = parseDecimal(row.lowVolts);
    const lowP = parseDecimal(row.lowPercent);
    const highV = parseDecimal(row.highVolts);
    const highP = parseDecimal(row.highPercent);
    const cap = parseDecimal(row.capacity);
    if (![lowV, lowP, highV, highP].every(Number.isFinite)) {
      setError("В каждой точке укажите напряжение и процент");
      return;
    }
    if (lowP < 0 || lowP > 100 || highP < 0 || highP > 100) {
      setError("Процент заполнения от 0 до 100");
      return;
    }
    if (lowV === highV) {
      setError("Напряжения двух точек должны отличаться");
      return;
    }
    if (lowP === highP) {
      setError("Проценты двух точек должны отличаться");
      return;
    }
    setSavingId(`cal:${row.id}`);
    setError(null);
    try {
      const st = await api.calibrateTank({
        station_id: stationId,
        tank_id: row.id,
        low_volts: lowV,
        low_percent: lowP,
        high_volts: highV,
        high_percent: highP,
        capacity_liters: Number.isFinite(cap) && cap > 0 ? cap : undefined,
      });
      const summary = calibrationSummary(
        st.cal_low_volts ?? lowV,
        st.cal_low_percent ?? lowP,
        st.cal_high_volts ?? highV,
        st.cal_high_percent ?? highP
      );
      setRows((current) =>
        current.map((item) =>
          item.id === row.id
            ? {
                ...item,
                calibrated: st.calibrated,
                lowVolts: st.cal_low_volts != null ? String(st.cal_low_volts) : String(lowV),
                lowPercent: st.cal_low_percent != null ? String(st.cal_low_percent) : String(lowP),
                highVolts: st.cal_high_volts != null ? String(st.cal_high_volts) : String(highV),
                highPercent:
                  st.cal_high_percent != null ? String(st.cal_high_percent) : String(highP),
                calSummary: summary,
              }
            : item
        )
      );
      toast.ok(`Калибровка ${row.code} сохранена (${summary})`);
      onChanged?.();
    } catch (err) {
      setError(messageOf(err, "Не удалось сохранить калибровку"));
    } finally {
      setSavingId(null);
    }
  }

  async function submitManualLevel(row: Row) {
    const lit = Number(row.manualLiters.replace(",", "."));
    if (!Number.isFinite(lit) || lit < 0) {
      setError("Укажите корректный остаток в литрах (≥ 0)");
      return;
    }
    setSavingId(`lvl:${row.id}`);
    setError(null);
    try {
      await api.ingestLevel({
        station_id: stationId,
        tank_id: row.id,
        actual_remainder_liters: lit,
        recorded_at: new Date().toISOString(),
      });
      setRows((current) =>
        current.map((item) =>
          item.id === row.id ? { ...item, actualLiters: lit, online: true } : item
        )
      );
      toast.ok(`Замер остатка ${row.code}: ${Math.round(lit)} л опубликован`);
      onChanged?.();
    } catch (err) {
      setError(messageOf(err, "Не удалось сохранить"));
    } finally {
      setSavingId(null);
    }
  }

  async function submitReceipt(row: Row) {
    const lit = Number(row.receiptLiters.replace(",", "."));
    if (!Number.isFinite(lit) || lit <= 0) {
      setError("Укажите принятый объём слива (> 0 л)");
      return;
    }
    setSavingId(`rec:${row.id}`);
    setError(null);
    try {
      await api.ingestReceipt({
        station_id: stationId,
        tank_id: row.id,
        volume_liters: lit,
        recorded_at: new Date().toISOString(),
      });
      setRows((current) =>
        current.map((item) =>
          item.id === row.id
            ? {
                ...item,
                receiptLiters: "",
                manualLiters: String(
                  Math.min(Number(item.capacity) || 20000, (Number(item.manualLiters) || 0) + lit)
                ),
              }
            : item
        )
      );
      toast.ok(`Приход ${Math.round(lit)} л принят на ${row.code}`);
      onChanged?.();
    } catch (err) {
      setError(messageOf(err, "Не удалось сохранить"));
    } finally {
      setSavingId(null);
    }
  }

  async function copyApi(row: Row) {
    const text = `${ingestUrl(row.path)}\nX-Device-Token: ${row.token}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(row.id);
    } catch {
      setCopied(null);
      setError("Не удалось скопировать адрес");
    }
  }

  return (
    <div className="tank-rows">
      <p className="dash-muted">
        {canManage
          ? "Управление ёмкостями АГЗС: настройка объёма, подключение датчиков Shelly, калибровка и перевыпуск токенов."
          : "Ключ резервуара и адрес приёма. Карточку и датчик меняет администратор."}
      </p>
      {loading ? <p className="dash-muted">Загрузка…</p> : null}
      {rows.map((row) => {
        const isExpanded = expandedToolsId === row.id;
        const measured = live?.tanks.find((tank) => tank.code === row.code);
        const ov = initialStates?.find((item) => item.id === row.id);
        const rem = measured?.remainder_liters ?? ov?.actual_remainder_liters ?? row.actualLiters;
        const capNum = Number(row.capacity) || 0;
        const fillPct =
          measured?.fill_percent ??
          ov?.fill_percent ??
          (rem != null && capNum > 0 ? Math.round((rem / capNum) * 100) : null);

        return (
          <div className="tank-block" key={row.id}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              {measured ? (
                <span className={`badge ${tankSensorBadge(measured)}`}>
                  {tankSensorLabel(measured)}
                </span>
              ) : ov ? (
                <span
                  className={`badge ${
                    ov.actual_remainder_liters == null ? "warn" : ov.online ? "ok" : "danger"
                  }`}
                >
                  {ov.actual_remainder_liters == null
                    ? "замера нет"
                    : ov.online
                      ? "датчик работает"
                      : "нет связи"}
                </span>
              ) : (
                <span className="badge warn">
                  {row.actualLiters == null ? "замера нет" : "телеметрия"}
                </span>
              )}
              <span className={`badge ${row.calibrated ? "ok" : "warn"}`}>
                {row.calibrated
                  ? `Откалиброван${row.calSummary ? `: ${row.calSummary}` : ""}`
                  : "Не откалиброван"}
              </span>
              <span className="dash-muted">
                {rem == null
                  ? "количество газа ещё не пришло"
                  : `${liters(rem)} из ${liters(capNum)}`}
                {fillPct != null ? ` · ${Math.round(fillPct)}%` : ""}
              </span>
            </div>

            <div className="tank-row">
              <label>
                Код резервуара
                <input
                  value={row.code}
                  readOnly={!canManage}
                  onChange={(event) =>
                    setRows((current) =>
                      current.map((item) =>
                        item.id === row.id ? { ...item, code: event.target.value } : item
                      )
                    )
                  }
                />
              </label>
              <label>
                Объём, л
                <input
                  inputMode="decimal"
                  value={row.capacity}
                  readOnly={!canManage}
                  onChange={(event) =>
                    setRows((current) =>
                      current.map((item) =>
                        item.id === row.id ? { ...item, capacity: event.target.value } : item
                      )
                    )
                  }
                />
              </label>
              {canManage ? (
                <div className="tank-row-btns">
                  <button
                    type="button"
                    className="btn small"
                    disabled={savingId === row.id}
                    onClick={() => saveRow(row)}
                  >
                    Сохранить
                  </button>
                  <button
                    type="button"
                    className="btn secondary small"
                    onClick={() => setExpandedToolsId(isExpanded ? null : row.id)}
                  >
                    {isExpanded ? "Скрыть замер/калибровку" : "Замер и калибровка"}
                  </button>
                  <button
                    type="button"
                    className="btn secondary small text-danger"
                    disabled={savingId === `del:${row.id}`}
                    onClick={() => setPendingAction({ kind: "delete", row })}
                  >
                    Удалить
                  </button>
                </div>
              ) : null}
            </div>

            {canManage ? (
              <>
                <form
                  className="shelly-line"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void connectShelly(row);
                  }}
                >
                  <label>
                    Shelly IP (локальная сеть датчика)
                    <input
                      placeholder="192.168.0.104"
                      value={row.shellyHost}
                      onChange={(event) =>
                        setRows((current) =>
                          current.map((item) =>
                            item.id === row.id ? { ...item, shellyHost: event.target.value } : item
                          )
                        )
                      }
                    />
                  </label>
                  <button
                    type="submit"
                    className="btn small"
                    disabled={savingId === `shelly:${row.id}` || !row.shellyHost.trim()}
                  >
                    {savingId === `shelly:${row.id}`
                      ? "Проверяю…"
                      : row.shelly?.host === row.shellyHost.trim()
                        ? "Проверить"
                        : "Подключить"}
                  </button>
                  {row.shelly ? (
                    <button
                      type="button"
                      className="btn secondary small"
                      disabled={savingId === `shelly:${row.id}`}
                      onClick={() => disconnectShelly(row)}
                    >
                      Отключить
                    </button>
                  ) : null}
                  <p className={row.shelly?.online ? "shelly-status online" : "shelly-status"}>
                    {shellyText(row.shelly, savingId === `shelly:${row.id}`)}
                  </p>
                </form>

                {isExpanded && (
                  <div className="tank-tools-grid">
                    <div className="tank-tool-box">
                      <strong>Ручной ввод остатка (публикуется на лэндинге)</strong>
                      <div className="tank-tool-inline">
                        <label>
                          Фактический остаток, л
                          <input
                            inputMode="decimal"
                            value={row.manualLiters}
                            onChange={(e) =>
                              setRows((cur) =>
                                cur.map((it) =>
                                  it.id === row.id ? { ...it, manualLiters: e.target.value } : it
                                )
                              )
                            }
                          />
                        </label>
                        <button
                          type="button"
                          className="btn small"
                          disabled={savingId === `lvl:${row.id}`}
                          onClick={() => submitManualLevel(row)}
                        >
                          Обновить остаток
                        </button>
                      </div>
                    </div>

                    <div className="tank-tool-box">
                      <strong>Оформить приход / слив в резервуар</strong>
                      <div className="tank-tool-inline">
                        <label>
                          Принятый объём, л
                          <input
                            inputMode="decimal"
                            placeholder="4500"
                            value={row.receiptLiters}
                            onChange={(e) =>
                              setRows((cur) =>
                                cur.map((it) =>
                                  it.id === row.id ? { ...it, receiptLiters: e.target.value } : it
                                )
                              )
                            }
                          />
                        </label>
                        <button
                          type="button"
                          className="btn small"
                          disabled={savingId === `rec:${row.id}`}
                          onClick={() => submitReceipt(row)}
                        >
                          Записать приход
                        </button>
                      </div>
                    </div>

                    <div className="tank-tool-box">
                      <strong>Калибровка датчика</strong>
                      <p className="dash-muted">
                        Две точки со шкалы резервуара: напряжение с датчика и процент на циферблате.
                      </p>
                      {row.shelly?.volts != null ? (
                        <p className="dash-muted">
                          Сейчас на датчике{" "}
                          {row.shelly.volts.toLocaleString("ru-RU", {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2,
                          })}{" "}
                          В
                        </p>
                      ) : null}
                      <div className="tank-tool-inline">
                        <label>
                          Точка 1, В
                          <input
                            inputMode="decimal"
                            placeholder="1,2"
                            value={row.lowVolts}
                            onChange={(e) =>
                              setRows((cur) =>
                                cur.map((it) =>
                                  it.id === row.id ? { ...it, lowVolts: e.target.value } : it
                                )
                              )
                            }
                          />
                        </label>
                        <label>
                          Точка 1, %
                          <input
                            inputMode="decimal"
                            placeholder="20"
                            value={row.lowPercent}
                            onChange={(e) =>
                              setRows((cur) =>
                                cur.map((it) =>
                                  it.id === row.id ? { ...it, lowPercent: e.target.value } : it
                                )
                              )
                            }
                          />
                        </label>
                        <label>
                          Точка 2, В
                          <input
                            inputMode="decimal"
                            placeholder="3,8"
                            value={row.highVolts}
                            onChange={(e) =>
                              setRows((cur) =>
                                cur.map((it) =>
                                  it.id === row.id ? { ...it, highVolts: e.target.value } : it
                                )
                              )
                            }
                          />
                        </label>
                        <label>
                          Точка 2, %
                          <input
                            inputMode="decimal"
                            placeholder="80"
                            value={row.highPercent}
                            onChange={(e) =>
                              setRows((cur) =>
                                cur.map((it) =>
                                  it.id === row.id ? { ...it, highPercent: e.target.value } : it
                                )
                              )
                            }
                          />
                        </label>
                        <button
                          type="button"
                          className="btn secondary small"
                          disabled={savingId === `cal:${row.id}`}
                          onClick={() => submitCalibration(row)}
                        >
                          Сохранить калибровку
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </>
            ) : row.shellyHost ? (
              <p className="dash-muted">Shelly: {row.shellyHost}</p>
            ) : null}

            {canManage ? (
              <div className="tank-api">
                <span>API датчика</span>
                <code>{ingestUrl(row.path)}</code>
                <code>X-Device-Token: {row.token}</code>
                <button type="button" className="btn secondary small" onClick={() => copyApi(row)}>
                  {copied === row.id ? "Скопировано" : "Копировать"}
                </button>
                <button
                  type="button"
                  className="btn secondary small"
                  disabled={savingId === `rot:${row.id}`}
                  onClick={() => setPendingAction({ kind: "rotate", row })}
                >
                  Перевыпустить токен
                </button>
              </div>
            ) : null}
          </div>
        );
      })}
      {canManage ? (
        <div className="tank-block">
          <div className="tank-row">
            <label>
              Новый резервуар (код)
              <input
                placeholder="R-2"
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
            </label>
            <label>
              Объём, л
              <input
                placeholder="10000"
                inputMode="decimal"
                value={capacity}
                onChange={(event) => setCapacity(event.target.value)}
              />
            </label>
            <button
              type="button"
              className="btn small"
              disabled={savingId === "new"}
              onClick={addTank}
            >
              Добавить резервуар
            </button>
          </div>
        </div>
      ) : null}
      {error ? <p className="tank-error">{error}</p> : null}

      <ConfirmModal
        open={pendingAction !== null}
        title={
          pendingAction?.kind === "delete"
            ? `Удалить резервуар ${pendingAction.row.code}?`
            : `Перевыпустить токен ${pendingAction?.row.code ?? ""}?`
        }
        message={
          pendingAction?.kind === "delete"
            ? "Резервуар и его токен будут удалены, а показания перестанут поступать."
            : "Текущий X-Device-Token перестанет приниматься сервером."
        }
        details={
          pendingAction?.kind === "rotate"
            ? "После перевыпуска обновите токен на Shelly и station-edge."
            : undefined
        }
        confirmLabel={pendingAction?.kind === "delete" ? "Удалить резервуар" : "Перевыпустить токен"}
        danger
        busy={
          pendingAction != null &&
          savingId === `${pendingAction.kind === "delete" ? "del" : "rot"}:${pendingAction.row.id}`
        }
        onConfirm={() => void confirmPendingAction()}
        onCancel={() => setPendingAction(null)}
      />
    </div>
  );
}

function toRow(
  device: TankDevice,
  state?: AdminTankOverview | TankIngestState | null
): Row {
  const actual = state?.actual_remainder_liters ?? null;
  const lowV = state?.cal_low_volts;
  const lowP = state?.cal_low_percent;
  const highV = state?.cal_high_volts;
  const highP = state?.cal_high_percent;
  const calibrated = state?.calibrated ?? false;
  return {
    id: device.id,
    code: device.code,
    capacity: String(device.capacity_liters),
    token: device.ingest_token ?? "",
    path: device.ingest_url || device.level_path,
    shellyHost: device.shelly?.host ?? "",
    shelly: device.shelly,
    lowVolts: lowV != null ? String(lowV) : "",
    lowPercent: lowP != null ? String(lowP) : "",
    highVolts: highV != null ? String(highV) : "",
    highPercent: highP != null ? String(highP) : "",
    calibrated,
    calSummary: calibrated ? calibrationSummary(lowV, lowP, highV, highP) : null,
    manualLiters:
      actual != null
        ? String(Math.round(actual))
        : String(Math.round(device.capacity_liters * 0.5)),
    receiptLiters: "",
    actualLiters: actual,
    online: state && "online" in state ? state.online : false,
  };
}

function parseDecimal(raw: string): number {
  const text = raw.trim().replace(",", ".");
  if (!text) return Number.NaN;
  return Number(text);
}

function calibrationSummary(
  lowV: number | null | undefined,
  lowP: number | null | undefined,
  highV: number | null | undefined,
  highP: number | null | undefined
): string | null {
  if (lowV == null || highV == null) return null;
  const left = lowP != null ? `${lowV} В = ${lowP}%` : `${lowV} В`;
  const right = highP != null ? `${highV} В = ${highP}%` : `${highV} В`;
  return `${left} … ${right}`;
}

function shellyText(link: ShellyLink | null, pending: boolean): string {
  if (pending) return "Проверяю Shelly…";
  if (!link) return "Сервер сам опросит прибор по этому IP.";
  if (!link.online) return link.last_error || "Нет связи";
  const parts = ["На связи"];
  if (link.model) parts.push(link.model);
  if (link.firmware) parts.push(link.firmware);
  if (link.rssi != null) parts.push(`${link.rssi} dBm`);
  if (link.volts != null) {
    parts.push(
      `${link.volts.toLocaleString("ru-RU", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })} В`
    );
  } else if (link.sensor_ready) {
    parts.push("напряжения нет");
  } else {
    parts.push("вольтметр не включён");
  }
  if (link.applied) parts.push("записано в остаток");
  else if (link.volts != null && !link.last_error) parts.push("в остаток после калибровки");
  else if (link.last_error) parts.push(link.last_error);
  return parts.join(" · ");
}
