import { fiscalCheck } from "../sim/engine";
import type { StationDetail } from "../types";
import { fiscalBadge, fiscalText, liters, tenge, timeHM } from "../format";

/** Счётчик ТРК → чек на онлайн-ККМ → ОФД → КГД */
export default function FiscalCheckTable({ station }: { station: StationDetail }) {
  const fc = fiscalCheck(station);

  return (
    <div className="fiscal">
      <div className="fiscal-chain">
        <div className="fiscal-step">
          <span>Счётчики ТРК</span>
          <strong>{liters(fc.counter_liters)}</strong>
          <em>{fc.fills} заправок</em>
        </div>
        <div className={`fiscal-link${fc.unreceipted_liters ? " bad" : ""}`}>
          {fc.unreceipted_liters ? `без чека ${liters(fc.unreceipted_liters)}` : "→"}
        </div>
        <div className="fiscal-step">
          <span>Онлайн-ККМ</span>
          <strong>{liters(fc.kkm_liters)}</strong>
          <em>{fc.kkm_receipts} чеков</em>
        </div>
        <div className={`fiscal-link${fc.unsent_liters ? " warn" : ""}`}>
          {fc.unsent_liters ? `не передано ${liters(fc.unsent_liters)}` : "→"}
        </div>
        <div className="fiscal-step">
          <span>ОФД → КГД</span>
          <strong>{liters(fc.ofd_liters)}</strong>
          <em>
            {fc.ofd_receipts} чеков · {tenge(fc.ofd_amount_kzt)}
          </em>
        </div>
      </div>

      <div className="dash-table-wrap">
        <table className="dash-table">
          <thead>
            <tr>
              <th>Колонка · ККМ</th>
              <th>Счётчик ТРК</th>
              <th>Чеки ККМ</th>
              <th>Получено ОФД</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {fc.pumps.map((p) => (
              <tr key={p.id}>
                <td>
                  <strong>{p.code}</strong>
                  <div className="dash-muted">
                    {p.kkm_serial} · {p.kkm_online ? "онлайн" : "автономный режим"}
                  </div>
                </td>
                <td>
                  {liters(p.counter_liters)}
                  <div className="dash-muted">{p.fills} заправок</div>
                </td>
                <td>
                  {liters(p.kkm_liters)}
                  <div className="dash-muted">{p.kkm_receipts} чеков</div>
                </td>
                <td>
                  {liters(p.ofd_liters)}
                  <div className="dash-muted">
                    {p.ofd_receipts} чеков · посл. {timeHM(p.ofd_last_at)}
                  </div>
                </td>
                <td>
                  <span className={`badge ${fiscalBadge(p.status)}`}>
                    {p.status === "no_receipt"
                      ? `без чека ${liters(p.unreceipted_liters)} · ${p.fills - p.kkm_receipts} запр.`
                      : p.status === "not_sent"
                        ? `не передано ${p.unsent_receipts} чек. · ${liters(p.unsent_liters)}`
                        : fiscalText(p.status)}
                  </span>
                </td>
              </tr>
            ))}
            <tr className="dash-total">
              <td>Итого</td>
              <td>{liters(fc.counter_liters)}</td>
              <td>{liters(fc.kkm_liters)}</td>
              <td>{liters(fc.ofd_liters)}</td>
              <td>{fc.gap_liters ? `КГД не видит ${tenge(fc.gap_kzt)}` : "—"}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
