/** Та же полоса, что в backend/app/domain/balance.py. Датчик — ориентир, колонка — учёт. */

export const SENSOR_BAND_FLOOR_LITERS = 100;
export const SENSOR_BAND_FRACTION = 0.02;
export const UNMETERED_DROP_FLOOR_LITERS = 300;
export const UNMETERED_DROP_FRACTION = 0.03;
export const UNREGISTERED_RISE_LITERS = 1000;
export const DISPENSE_NEAR_ZERO_LITERS = 20;

export function sensorBandLiters(capacityLiters: number | null | undefined): number {
  if (capacityLiters == null || !Number.isFinite(capacityLiters) || capacityLiters <= 0) {
    return SENSOR_BAND_FLOOR_LITERS;
  }
  return Math.max(SENSOR_BAND_FLOOR_LITERS, capacityLiters * SENSOR_BAND_FRACTION);
}

export function unmeteredDropLiters(capacityLiters: number | null | undefined): number {
  if (capacityLiters == null || !Number.isFinite(capacityLiters) || capacityLiters <= 0) {
    return UNMETERED_DROP_FLOOR_LITERS;
  }
  return Math.max(UNMETERED_DROP_FLOOR_LITERS, capacityLiters * UNMETERED_DROP_FRACTION);
}

export type SensorCue = {
  status: "ok" | "warn";
  note: string;
};

export function sensorCue(args: {
  discrepancyLiters: number | null;
  outflowLiters: number | null;
  dispensedLiters: number;
  capacityLiters?: number | null;
}): SensorCue {
  if (args.outflowLiters == null && args.discrepancyLiters == null) {
    return { status: "ok", note: "датчик недоступен" };
  }
  const band = sensorBandLiters(args.capacityLiters);
  const outflow = args.outflowLiters;
  if (outflow != null && outflow <= -UNREGISTERED_RISE_LITERS) {
    return { status: "warn", note: "слив без документа" };
  }
  if (
    outflow != null &&
    outflow >= unmeteredDropLiters(args.capacityLiters) &&
    args.dispensedLiters <= DISPENSE_NEAR_ZERO_LITERS
  ) {
    return { status: "warn", note: "уход без колонки" };
  }
  const bandLabel = `±${Math.round(band).toLocaleString("ru-RU")} л`;
  if (args.discrepancyLiters != null && Math.abs(args.discrepancyLiters) > band) {
    return { status: "ok", note: `датчик вне полосы ${bandLabel}` };
  }
  return { status: "ok", note: `ориентир ${bandLabel}` };
}
