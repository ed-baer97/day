import { useState, type ReactNode } from "react";
import { liters, tenge } from "../format";
import { SRC } from "../sources";
import type { SensorStatus } from "../types";

export interface ColumnOperation {
  id: string;
  pump: string;
  liters: number;
  price: number;
  amount: number;
  time: string;
  state: "done" | "pouring";
  link: SensorStatus;
}

export default function ColumnCard({
  title,
  dispensedLabel,
  dispensed,
  operation,
  volume,
  pricePerLiter,
  time,
  link,
  operations,
  note,
}: {
  title: string;
  dispensedLabel: string;
  dispensed: number | null;
  operation: string;
  volume: number | null;
  pricePerLiter: number | null;
  time: string;
  link: string;
  operations: ColumnOperation[];
  note?: string | null;
}) {
  const [open, setOpen] = useState(false);

  return (
    <article className="column-card">
      <h3>{title}</h3>
      <p className="stage-vol">
        {dispensedLabel}: <strong>{dispensed == null ? "—" : liters(dispensed)}</strong>
      </p>
      {note ? <p className="stage-wait">{note}</p> : null}
      <dl className="kv">
        <Field label="Текущая операция" source={SRC.topaz}>
          {operation}
        </Field>
        <Field label="Объём" source={SRC.topaz}>
          {volume == null ? "—" : liters(volume)}
        </Field>
        <Field label="Цена" source={SRC.topaz}>
          {pricePerLiter == null ? "—" : `${tenge(pricePerLiter)}/л`}
        </Field>
        <Field label="Время" source={SRC.topaz}>
          {time}
        </Field>
        <Field label="Статус связи" source={`${SRC.rs232} · ${SRC.lte}`}>
          {link}
        </Field>
      </dl>
      <button type="button" className="btn secondary small column-more" onClick={() => setOpen((v) => !v)}>
        {open ? "Скрыть операции" : "Подробности операций"}
      </button>
      {open && (
        <div className="ops">
          {operations.length === 0 ? (
            <p className="stage-wait">Операций по этой поставке пока нет</p>
          ) : (
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Колонка</th>
                  <th>Объём</th>
                  <th>Сумма</th>
                  <th>Время</th>
                  <th>Связь</th>
                </tr>
              </thead>
              <tbody>
                {operations.map((op) => (
                  <tr key={op.id}>
                    <td>{op.pump}</td>
                    <td>
                      {liters(op.liters)}
                      {op.state === "pouring" ? <div className="dash-muted">идёт налив</div> : null}
                    </td>
                    <td>{tenge(op.amount)}</td>
                    <td>{op.time}</td>
                    <td>{op.link === "ok" ? "есть" : "нет связи"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      <p className="src-line">
        <span>Источник</span>
        {SRC.topaz} · {SRC.rs232} · {SRC.lte}
      </p>
    </article>
  );
}

function Field({
  label,
  source,
  children,
}: {
  label: string;
  source: string;
  children: ReactNode;
}) {
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
