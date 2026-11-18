import type { CatalogStation } from "../api/client";
import { dateTime, liters } from "../format";
import { isLowFill, type LiveLevel, SensorStatusBadge } from "../liveLevels";

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
      {live && live.tanks.length > 0 ? <SensorStatusBadge level={live} /> : null}
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
}) {
  return (
    <li className="st-list-item">
      <button type="button" className="st-row" onClick={onOpen}>
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
            <SensorStatusBadge level={live} />
          ) : (
            <span className="badge warn">не подключён</span>
          )}
        </div>
        <span className="st-row-chevron" aria-hidden>
          ›
        </span>
      </button>
    </li>
  );
}
