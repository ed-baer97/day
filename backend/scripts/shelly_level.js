// Shelly Plus Uni сам шлёт напряжение на сервер.
// Адрес и ключ подставляет install_shelly_level.py перед загрузкой.
// Прибор открывает соединение наружу, сервер в его сеть не заходит.

let SERVER_URL = "%%SERVER_URL%%";
let DEVICE_TOKEN = "%%DEVICE_TOKEN%%";
let INTERVAL_MS = 15000;

function isoFromUnix(unix) {
  return new Date(unix * 1000).toISOString();
}

function postLevel(volts, unix) {
  let payload = JSON.stringify({
    volts: volts,
    recorded_at: isoFromUnix(unix),
    source_event_id: "shelly-" + unix + "-" + Math.floor(Math.random() * 1000000)
  });
  Shelly.call(
    "HTTP.Request",
    {
      method: "POST",
      url: SERVER_URL,
      timeout: 10,
      headers: {
        "Content-Type": "application/json",
        "X-Device-Token": DEVICE_TOKEN
      },
      body: payload
    },
    function (response, errorCode, errorMessage) {
      if (errorCode !== 0) {
        print("отправка не удалась " + errorCode + " " + errorMessage);
        return;
      }
      let body = response && response.body ? response.body : "";
      print("вольты " + volts + " ответ " + response.code + " " + body);
    }
  );
}

function readAndSend() {
  Shelly.call("Shelly.GetStatus", {}, function (status, errorCode, errorMessage) {
    if (errorCode !== 0) {
      print("статус не прочитан " + errorCode + " " + errorMessage);
      return;
    }
    let meter = status["voltmeter:100"];
    if (!meter || typeof meter.voltage !== "number") {
      print("вольтметр молчит");
      return;
    }
    let unix = status.sys && status.sys.unixtime ? status.sys.unixtime : 0;
    if (!unix) {
      print("нет времени на Shelly");
      return;
    }
    postLevel(meter.voltage, unix);
  });
}

readAndSend();
Timer.set(INTERVAL_MS, true, readAndSend);
