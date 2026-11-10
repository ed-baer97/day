export default function AdminSecurityTab({
  username,
}: {
  username?: string | null;
}) {
  return (
    <div className="security-grid">
      <section className="dash-card">
        <h3>Разграничение публичных и конфиденциальных данных</h3>
        <p className="dash-muted">
          Соблюдение политики конфиденциальности: на публичном лэндинге (
          <code>GET /api/v1/public/levels</code>) публикуется только наличие газа на АГЗС.
        </p>
        <table className="dash-table" style={{ marginTop: 10 }}>
          <thead>
            <tr>
              <th>Категория данных</th>
              <th>Публичный лэндинг</th>
              <th>Админ-панель</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Название, код, адрес АГЗС и % / литры в резервуаре</td>
              <td>
                <span className="badge ok">Открыто (публично)</span>
              </td>
              <td>
                <span className="badge ok">Доступно</span>
              </td>
            </tr>
            <tr>
              <td>Книжный остаток, расхождения (недостача / излишек)</td>
              <td>
                <span className="badge danger">Скрыто (конфиденциально)</span>
              </td>
              <td>
                <span className="badge ok">Только с токеном админа</span>
              </td>
            </tr>
            <tr>
              <td>Сверка ТРК ↔ ККМ ↔ ОФД ↔ КГД (продажи без чека)</td>
              <td>
                <span className="badge danger">Скрыто (конфиденциально)</span>
              </td>
              <td>
                <span className="badge ok">Только с токеном админа</span>
              </td>
            </tr>
            <tr>
              <td>Госномера газовозов, GPS-трекинг, маршруты и партии</td>
              <td>
                <span className="badge danger">Скрыто (конфиденциально)</span>
              </td>
              <td>
                <span className="badge ok">Только с токеном админа</span>
              </td>
            </tr>
            <tr>
              <td>IP-адреса контроллеров Shelly и X-Device-Token резервуаров</td>
              <td>
                <span className="badge danger">Скрыто (конфиденциально)</span>
              </td>
              <td>
                <span className="badge ok">Только с токеном админа</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section className="dash-card">
        <h3>Активная защита и устранённые уязвимости</h3>
        <ul className="trail-list" style={{ marginTop: 10 }}>
          <li>
            <span className="title">Защита от утечки телеметрии на лэндинге</span>
            <span className="desc">
              Из фоновой карты лэндинга исключены газовозы, заводы, маршруты поставок и
              статусы расхождений; удалён глобальный объект <code>window.__lpgDebug</code>.
            </span>
          </li>
          <li>
            <span className="title">Защита API приёма телеметрии и IDOR-контроль</span>
            <span className="desc">
              Эндпоинты <code>/api/v1/ingest/*</code> требуют валидный <code>X-Device-Token</code>{" "}
              или <code>Bearer</code>-токен администратора; токен резервуара привязан строго к
              своему <code>tank_id</code> и <code>station_id</code>.
            </span>
          </li>
          <li>
            <span className="title">Защита от SSRF при опросе датчиков Shelly</span>
            <span className="desc">
              Валидатор хостов блокирует обращение к <code>localhost</code>, <code>127.0.0.0/8</code>,{" "}
              <code>169.254.0.0/16</code> (cloud metadata), <code>0.0.0.0</code> и внутренним
              контейнерам инфраструктуры.
            </span>
          </li>
          <li>
            <span className="title">Rate-Limiting входа и отзыв токенов при выходе</span>
            <span className="desc">
              Защита от брутфорса (не более 5 неудачных попыток за 60 секунд → HTTP 429) и
              серверный отзыв токена (<code>POST /api/v1/auth/logout</code> с проверкой{" "}
              <code>jti</code>).
            </span>
          </li>
          <li>
            <span className="title">Текущая сессия администратора</span>
            <span className="desc">
              Пользователь: <strong>{username}</strong> · Хранение: <code>sessionStorage</code>{" "}
              (автоматическая очистка при закрытии вкладки + отзыв <code>jti</code> при выходе)
            </span>
          </li>
        </ul>
      </section>
    </div>
  );
}
