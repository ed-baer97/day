import type { CatalogStation } from "../api/client";
import { dateTime, liters } from "../format";
import { isLowFill, type LiveLevel, SensorStatus } from "../liveLevels";

export function FillCell({
  fill,
  gas,
  cap,
  free,
  live,
}: {
  fill: number | null;
  gas: number | null;
  cap: number;
  free: number | null;
  live: LiveLevel | null;
}) {
  return (
    <div className="st-row-fill">
      <div className="fill-bar">
        <i
          style={{
            width: `${fill ?? 0}%`,
            background: isLowFill(fill) ? "var(--coral)" : "var(--sea)",
          }}
        />
      </div>
      <span>
        {gas == null ? "замера нет" : `${liters(gas)} из ${liters(cap)}`} ·{" "}
        <strong className={isLowFill(fill) ? "text-danger" : ""}>
          {fill == null ? "—" : `${fill}%`}
        </strong>
        {free != null ? ` (своб. ${liters(free)})` : ""}
      </span>
      {live && live.tanks.length > 0 ? <SensorStatus level={live} /> : null}
    </div>
  );
}

export default function StationListRow({
  station,
  region,
  fill,
  gas,
  cap,
  free,
  live,
  hasTanks,
  spent,
  spentCaption,
  onOpen,
  onMap,
  onAdmin,
}: {
  station: CatalogStation;
  region: string;
  fill: number | null;
  gas: number | null;
  cap: number;
  free: number | null;
  live: LiveLevel | null;
  hasTanks: boolean;
  spent: number | null;
  spentCaption: string;
  onOpen: () => void;
  onMap?: () => void;
  onAdmin?: () => void;
}) {
  return (
    <li className="st-list-item">
      <div className="st-row" onClick={onOpen}>
        <div className="st-row-main">
          <strong>{station.name}</strong>
          <span>
            {station.code} · {region}
            {station.address ? ` · ${station.address}` : ""}
          </span>
        </div>
        <FillCell fill={fill} gas={gas} cap={cap} free={free} live={hasTanks ? live : null} />
        <div className="st-row-num">
          <strong>{spent == null ? "—" : liters(spent)}</strong>
          <span>{spentCaption}</span>
        </div>
        <div className="st-row-num">
          <strong>{live?.tanks.length ?? 0} резерв.</strong>
          <span>{live?.measuredAt ? dateTime(live.measuredAt) : "замера нет"}</span>
        </div>
        <div className="st-row-badges">
          {hasTanks && live ? (
            <SensorStatus level={live} />
          ) : (
            <span className="badge warn">не подключён</span>
          )}
        </div>
        <div className="st-row-actions" onClick={(event) => event.stopPropagation()}>
          <button type="button" className="btn secondary small" onClick={onOpen}>
            Сводка
          </button>
          {onMap ? (
            <button type="button" className="btn secondary small" onClick={onMap}>
              Карта
            </button>
          ) : null}
          {onAdmin ? (
            <button type="button" className="btn secondary small" onClick={onAdmin}>
              Админка
            </button>
          ) : null}
        </div>
      </div>
    </li>
  );
}
