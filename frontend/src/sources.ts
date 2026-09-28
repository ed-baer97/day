/** Откуда в интерфейсе берётся каждый показатель. */
export const SRC = {
  factory: "документы отгрузки",
  gps: "GPS",
  quantity: "датчик количества",
  temperature: "температура",
  rochester: "Rochester Junior",
  srg: "SRG-1-WAVE",
  bluetooth: "Bluetooth",
  phone: "смартфон АГЗС",
  topaz: "Topaz-119-28M",
  rs232: "RS-232",
  lte: "LTE-шлюз",
  fiscal: "фискальная система / уполномоченный орган",
} as const;
