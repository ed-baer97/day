import { useMemo, type ReactNode } from "react";
import {
  celsius,
  columnLabel,
  dateTime,
  linkText,
  liters,
  sensorText,
  supplyStatusText,
  tenge,
  vsBase,
} from "../format";
import { useSim } from "../sim/SimContext";
import { supplyTank } from "../sim/supply";
import { SRC } from "../sources";
import type { LpgSupply, SensorStatus } from "../types";
import ColumnCard, { type ColumnOperation } from "./ColumnCard";

export default function SupplyPage({
  supplyId,
  onSelect,
}: {
  supplyId: string | null;
  onSelect: (id: string) => void;
}) {
  const { state } = useSim();
  const supplies = state.supplies;
  const supply = supplies.find((s) => s.supply_id === supplyId) ?? supplies[0] ?? null;

  if (!supply) {
    return (
      <div className="dash">
        <p className="empty">Поставок пока нет</p>
      </div>
    );
  }

  return (
    <div className="dash">
      <header className="dash-hero">
        <p className="kicker">Поставка LPG · {supply.supply_id}</p>
        <h2>
          {supply.factory_name} → {supply.plate} → {supply.station_name}
        </h2>
        <p className="dash-muted">
          Резервуар {supply.tank_code} · {dateTime(supply.shipped_at)} · {supplyStatusText(supply.status)}
        </p>
      </header>

      <div className="supply-picks" role="tablist" aria-label="Поставки">
        {supplies.map((s) => (
          <button
            key={s.supply_id}
            type="button"
            className={`supply-pick${s.supply_id === supply.supply_id ? " active" : ""}`}
            onClick={() => onSelect(s.supply_id)}
          >
            {s.supply_id} · {supplyStatusText(s.status)}
          </button>
        ))}
      </div>

      <VolumeStrip supply={supply} />
      <FactoryStage supply={supply} />
      <TruckStage supply={supply} />
      <TankStage supply={supply} />
      <ColumnStage supply={supply} />
      <FiscalStage supply={supply} />
    </div>
  );
}

function VolumeStrip({ supply }: { supply: LpgSupply }) {
  const cells = [
    ["Отгружено", supply.shipped_liters, null],
    ["Доставлено", supply.delivered_liters, supply.delivered_liters != null ? vsBase(supply.delivered_liters, supply.shipped_liters, "отгрузке") : null],
    ["Принято", supply.accepted_liters, supply.accepted_liters != null && supply.delivered_liters != null ? vsBase(supply.accepted_liters, supply.delivered_liters, "доставке") : null],
    ["Отпущено", supply.dispensed_liters > 0 || supply.accepted_liters != null ? supply.dispensed_liters : null, null],
    ["Фискальный", supply.fiscal_updated_at ? supply.fiscal_liters : null, supply.fiscal_updated_at ? vsBase(supply.fiscal_liters, supply.dispensed_liters, "отпуску") : null],
  ] as const;

  return (
    <div className="supply-vols">
      {cells.map(([label, value, delta]) => (
        <div key={label} className="supply-vol">
          <span>{label}</span>
          <strong>{value == null ? "—" : liters(value)}</strong>
          {delta ? <em>{delta}</em> : null}
        </div>
      ))}
    </div>
  );
}

function FactoryStage({ supply }: { supply: LpgSupply }) {
  return (
    <section className="stage">
      <StageHead n={1} title="Отгрузка с завода" />
      <p className="stage-vol">
        Отгружено: <strong>{liters(supply.shipped_liters)}</strong>
      </p>
      <dl className="kv">
        <Field label="Завод" source={SRC.factory}>
          {supply.factory_name}
        </Field>
        <Field label="Дата и время" source={SRC.factory}>
          {dateTime(supply.shipped_at)}
        </Field>
        <Field label="Партия / накладная" source={SRC.factory}>
          {supply.waybill}
        </Field>
        <Field label="Объём" source={SRC.factory}>
          {liters(supply.shipped_liters)}
        </Field>
        <Field label="Температура" source={SRC.factory}>
          {celsius(supply.shipped_temp_c)}
        </Field>
      </dl>
      <Source items={[SRC.factory]} />
    </section>
  );
}

function TruckStage({ supply }: { supply: LpgSupply }) {
  const qty = supply.delivered_liters;
  return (
    <section className="stage">
      <StageHead n={2} title="Газовоз" />
      <p className="stage-vol">
        Количество: <strong>{qty == null ? "—" : liters(qty)}</strong>
      </p>
      {qty != null ? <p className="stage-delta">{vsBase(qty, supply.shipped_liters, "отгрузке")}</p> : null}
      <dl className="kv">
        <Field label="Газовоз" source={SRC.gps}>
          {supply.plate}
        </Field>
        <Field label="GPS" source={SRC.gps}>
          {supply.gps_lat != null && supply.gps_lon != null
            ? `${supply.gps_lat.toFixed(4)}, ${supply.gps_lon.toFixed(4)}`
            : "—"}
        </Field>
        <Field label="Маршрут" source={SRC.gps}>
          {supply.route_name}
        </Field>
        <Field label="Время отправления" source={SRC.gps}>
          {dateTime(supply.departed_at)}
        </Field>
        <Field label="Время прибытия" source={SRC.gps}>
          {dateTime(supply.arrived_at)}
        </Field>
        <Field label="Температура" source={SRC.temperature}>
          {celsius(supply.truck_temp_c)}
        </Field>
        <Field label="Количество LPG" source={SRC.quantity}>
          {qty == null ? "—" : liters(qty)}
        </Field>
        <Field label="Датчики" source={`${SRC.gps} · ${SRC.quantity} · ${SRC.temperature}`}>
          {sensorLine(supply)}
        </Field>
      </dl>
      <Source items={[SRC.gps, SRC.quantity, SRC.temperature]} />
    </section>
  );
}

function TankStage({ supply }: { supply: LpgSupply }) {
  const { state } = useSim();
  const { tank } = useMemo(() => supplyTank(state, supply), [state, supply]);
  const cap = tank?.capacity_liters ?? 0;
  const vol = tank?.actual_remainder_liters ?? null;
  const pct = cap && vol != null ? Math.min(100, Math.round((vol / cap) * 100)) : null;
  const accepted = supply.accepted_liters != null;

  return (
    <section className="stage">
      <StageHead n={3} title="Хранилище АГЗС" />
      <p className="stage-kicker">Цифровой уровень резервуара · {SRC.rochester}</p>
      {accepted ? (
        <p className="stage-vol">
          Принято: <strong>{liters(supply.accepted_liters)}</strong>
        </p>
      ) : (
        <p className="stage-wait">Поставка ещё не принята в резервуар {supply.tank_code}</p>
      )}
      {accepted && supply.delivered_liters != null ? (
        <p className="stage-delta">{vsBase(supply.accepted_liters!, supply.delivered_liters, "доставке")}</p>
      ) : null}
      {tank && pct != null && vol != null ? (
        <div className="gauge tank-gauge">
          <div className="gauge-bar" aria-hidden>
            <i style={{ height: `${pct}%` }} />
          </div>
          <dl className="kv gauge-fields">
            <Field label="Резервуар №" source={SRC.srg}>
              {tank.code}
            </Field>
            <Field label="Уровень" source={SRC.srg}>
              {pct}%
            </Field>
            <Field label="Объём LPG" source={SRC.srg}>
              {liters(vol)}
            </Field>
            <Field label="Температура" source={SRC.srg}>
              {celsius(tank.temperature_c)}
            </Field>
            <Field label="Время измерения" source={SRC.srg}>
              {dateTime(tank.last_measured_at)}
            </Field>
            <Field label="Смартфон / канал" source={`${SRC.bluetooth} · ${SRC.phone}`}>
              {tank.phone_label}
            </Field>
            <Field label="Качество связи" source={SRC.bluetooth}>
              {linkText(tank.link_quality)}
            </Field>
          </dl>
        </div>
      ) : (
        <p className="stage-wait">Нет измерения уровня</p>
      )}
      <p className="stage-wait">Показание датчика — весь резервуар, не только объём этой поставки.</p>
      <Source items={[SRC.srg, SRC.rochester, SRC.bluetooth, SRC.phone]} />
    </section>
  );
}

function ColumnStage({ supply }: { supply: LpgSupply }) {
  const pouring = supply.operations.find((op) => op.state === "pouring");
  const last = supply.operations[0];
  const ready = supply.accepted_liters != null || supply.dispensed_liters > 0;
  const operations: ColumnOperation[] = supply.operations.map((op) => ({
    id: op.id,
    pump: op.pump_code,
    liters: op.volume_liters,
    price: op.price_kzt_per_liter,
    amount: op.amount_kzt,
    time: dateTime(op.occurred_at),
    state: op.state,
    link: op.link_status,
  }));

  if (!ready) {
    return (
      <section className="stage">
        <StageHead n={4} title="Колонка АГЗС" />
        <p className="stage-wait">Колонка №1 ещё не отпускала эту поставку</p>
        <Source items={[SRC.topaz, SRC.rs232, SRC.lte]} />
      </section>
    );
  }

  return (
    <section className="stage">
      <StageHead n={4} title="Колонка АГЗС" />
      <ColumnCard
        title={columnLabel("1")}
        dispensedLabel="Отпущено"
        dispensed={supply.dispensed_liters}
        operation={pouring ? "налив" : "нет"}
        volume={pouring ? pouring.volume_liters : last?.volume_liters ?? null}
        pricePerLiter={pouring?.price_kzt_per_liter ?? last?.price_kzt_per_liter ?? null}
        time={pouring || last ? dateTime((pouring ?? last)!.occurred_at) : "—"}
        link={linkLabel(pouring?.link_status ?? last?.link_status ?? "ok")}
        operations={operations}
        note="по этой поставке"
      />
    </section>
  );
}

function FiscalStage({ supply }: { supply: LpgSupply }) {
  if (!supply.fiscal_updated_at) {
    return (
      <section className="stage">
        <StageHead n={5} title="Фискальные чеки" />
        <p className="stage-wait">Фискальных данных по этой поставке ещё нет</p>
        <Source items={[SRC.fiscal]} />
      </section>
    );
  }

  return (
    <section className="stage">
      <StageHead n={5} title="Фискальные чеки" />
      <p className="stage-vol">
        По фискальным данным: <strong>{liters(supply.fiscal_liters)}</strong>
      </p>
      <p className="stage-delta">{vsBase(supply.fiscal_liters, supply.dispensed_liters, "отпуску")}</p>
      <dl className="kv">
        <Field label="Количество чеков" source={SRC.fiscal}>
          {supply.fiscal_receipts}
        </Field>
        <Field label="Реализованный объём" source={SRC.fiscal}>
          {liters(supply.fiscal_liters)}
        </Field>
        <Field label="Сумма" source={SRC.fiscal}>
          {tenge(supply.fiscal_amount_kzt)}
        </Field>
        <Field label="Период" source={SRC.fiscal}>
          {supply.fiscal_period || "—"}
        </Field>
        <Field label="Обновлено" source={SRC.fiscal}>
          {dateTime(supply.fiscal_updated_at)}
        </Field>
      </dl>
      <Source items={[SRC.fiscal]} />
    </section>
  );
}

function StageHead({ n, title }: { n: number; title: string }) {
  return (
    <header className="stage-head">
      <span className="stage-n">{n}</span>
      <h3>{title}</h3>
    </header>
  );
}

function Field({ label, source, children }: { label: string; source: string; children: ReactNode }) {
  return (
    <>
      <dt>
        {label}
        <small className="src-tag">{source}</small>
      </dt>
      <dd>{children}</dd>
    </>
  );
}

function Source({ items }: { items: string[] }) {
  return (
    <p className="src-line">
      <span>Источник</span>
      {items.join(" · ")}
    </p>
  );
}

function sensorLine(supply: LpgSupply) {
  return `GPS ${sensorText(supply.gps_status)} · количество ${sensorText(supply.quantity_sensor)} · температура ${sensorText(supply.temp_sensor)}`;
}

function linkLabel(status: SensorStatus) {
  return status === "ok" ? "есть" : "нет связи";
}
