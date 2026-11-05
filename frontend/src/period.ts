export type PeriodPreset = "today" | "day" | "week" | "month";

export type ViewPeriod = {
  preset: PeriodPreset;
  /** Локальная дата-якорь, YYYY-MM-DD. Для «сегодня» не используется. */
  day: string;
};

export type TimeBucket = {
  startMs: number;
  endMs: number;
  label: string;
};

export type TimeRange = {
  preset: PeriodPreset;
  start: Date;
  end: Date;
  includesNow: boolean;
  /** Книга поставок не режется по дате — показываем её только за сегодняшний день. */
  countsReceipts: boolean;
  buckets: TimeBucket[];
  labels: string[];
  title: string;
  expenseTitle: string;
  inflowTitle: string;
  spentCaption: string;
  chartTitle: string;
  journalTitle: string;
  emptyJournal: string;
  indexAt: (timeMs: number) => number;
};

const WEEKDAYS = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

export function localDateKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function todayPeriod(now = new Date()): ViewPeriod {
  return { preset: "today", day: localDateKey(now) };
}

export function parseLocalDate(key: string): Date {
  const [year, month, day] = key.split("-").map(Number);
  return new Date(year, (month || 1) - 1, day || 1);
}

function startOfLocalDay(date: Date): Date {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

function addDays(date: Date, days: number): Date {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

function startOfWeek(date: Date): Date {
  const copy = startOfLocalDay(date);
  const weekday = copy.getDay();
  const shift = weekday === 0 ? -6 : 1 - weekday;
  copy.setDate(copy.getDate() + shift);
  return copy;
}

function dayMonth(date: Date): string {
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" }).format(date);
}

function monthTitle(date: Date, now: Date): string {
  const withYear = date.getFullYear() !== now.getFullYear();
  const text = new Intl.DateTimeFormat("ru-RU", {
    month: "long",
    year: withYear ? "numeric" : undefined,
  }).format(date);
  return text.replace(" г.", "");
}

function spanTitle(start: Date, endInclusive: Date): string {
  const sameMonth = start.getMonth() === endInclusive.getMonth() && start.getFullYear() === endInclusive.getFullYear();
  if (start.getTime() === startOfLocalDay(endInclusive).getTime()) return dayMonth(start);
  if (sameMonth) {
    const month = new Intl.DateTimeFormat("ru-RU", { month: "long" }).format(start);
    return `${start.getDate()}–${endInclusive.getDate()} ${month}`;
  }
  return `${dayMonth(start)} – ${dayMonth(endInclusive)}`;
}

function finish(range: Omit<TimeRange, "labels" | "indexAt"> & { buckets: TimeBucket[] }): TimeRange {
  const labels = range.buckets.map((bucket) => bucket.label);
  return {
    ...range,
    labels,
    indexAt(timeMs: number) {
      return range.buckets.findIndex((bucket) => timeMs >= bucket.startMs && timeMs < bucket.endMs);
    },
  };
}

function hourBuckets(day: Date): TimeBucket[] {
  const start = startOfLocalDay(day);
  return Array.from({ length: 24 }, (_, hour) => {
    const from = new Date(start);
    from.setHours(hour, 0, 0, 0);
    const to = new Date(start);
    to.setHours(hour + 1, 0, 0, 0);
    return {
      startMs: from.getTime(),
      endMs: to.getTime(),
      label: String(hour).padStart(2, "0"),
    };
  });
}

function dayBuckets(start: Date, count: number): TimeBucket[] {
  return Array.from({ length: count }, (_, index) => {
    const from = addDays(start, index);
    const to = addDays(from, 1);
    return {
      startMs: from.getTime(),
      endMs: to.getTime(),
      label: `${WEEKDAYS[from.getDay()]} ${from.getDate()}`,
    };
  });
}

export function resolveRange(period: ViewPeriod, now = new Date()): TimeRange {
  const today = startOfLocalDay(now);
  const requested = period.preset === "today" ? today : parseLocalDate(period.day);
  const anchor = requested.getTime() > today.getTime() ? today : startOfLocalDay(requested);

  if (period.preset === "today" || period.preset === "day") {
    const isToday = anchor.getTime() === today.getTime();
    const title = isToday && period.preset === "today" ? "сегодня" : dayMonth(anchor);
    const end = addDays(anchor, 1);
    return finish({
      preset: isToday && period.preset === "today" ? "today" : "day",
      start: anchor,
      end,
      includesNow: isToday,
      countsReceipts: isToday,
      buckets: hourBuckets(anchor),
      title,
      expenseTitle: isToday ? "Расход сегодня" : `Расход за ${title}`,
      inflowTitle: isToday ? "Приход сегодня" : `Приход за ${title}`,
      spentCaption: isToday ? "расход сегодня" : "расход за день",
      chartTitle: isToday ? "Остаток в резервуаре · сегодня" : `Остаток в резервуаре · ${title}`,
      journalTitle: isToday ? "Изменения остатка сегодня" : `Изменения остатка · ${title}`,
      emptyJournal: isToday ? "За сегодня смен остатка ещё не было." : `За ${title} смен остатка не было.`,
    });
  }

  if (period.preset === "week") {
    const start = startOfWeek(anchor);
    const end = addDays(start, 7);
    const title = spanTitle(start, addDays(end, -1));
    const includesNow = now.getTime() >= start.getTime() && now.getTime() < end.getTime();
    return finish({
      preset: "week",
      start,
      end,
      includesNow,
      countsReceipts: false,
      buckets: dayBuckets(start, 7),
      title,
      expenseTitle: `Расход за неделю ${title}`,
      inflowTitle: `Приход за неделю ${title}`,
      spentCaption: "расход за неделю",
      chartTitle: `Остаток в резервуаре · неделя ${title}`,
      journalTitle: `Изменения остатка · неделя ${title}`,
      emptyJournal: `За неделю ${title} смен остатка не было.`,
    });
  }

  const start = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const end = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1);
  const days = Math.round((end.getTime() - start.getTime()) / 86_400_000);
  const title = monthTitle(start, now);
  const includesNow = now.getTime() >= start.getTime() && now.getTime() < end.getTime();
  return finish({
    preset: "month",
    start,
    end,
    includesNow,
    countsReceipts: false,
    buckets: dayBuckets(start, days),
    title,
    expenseTitle: `Расход за ${title}`,
    inflowTitle: `Приход за ${title}`,
    spentCaption: "расход за месяц",
    chartTitle: `Остаток в резервуаре · ${title}`,
    journalTitle: `Изменения остатка · ${title}`,
    emptyJournal: `За ${title} смен остатка не было.`,
  });
}

export function shiftPeriod(period: ViewPeriod, delta: number, now = new Date()): ViewPeriod {
  const today = localDateKey(now);
  if (period.preset === "today") return { preset: "day", day: today };
  const anchor = parseLocalDate(period.day > today ? today : period.day);
  const next = new Date(anchor);
  if (period.preset === "month") next.setMonth(next.getMonth() + delta, 1);
  else if (period.preset === "week") next.setDate(next.getDate() + delta * 7);
  else next.setDate(next.getDate() + delta);
  const key = localDateKey(next);
  return { preset: period.preset, day: key > today ? today : key };
}

export function canShiftForward(period: ViewPeriod, now = new Date()): boolean {
  if (period.preset === "today") return false;
  const current = resolveRange(period, now);
  const next = resolveRange(shiftPeriod(period, 1, now), now);
  return next.start.getTime() > current.start.getTime() && next.start.getTime() <= startOfLocalDay(now).getTime();
}

export function periodKey(period: ViewPeriod): string {
  if (period.preset === "today") return "today";
  return `${period.preset}|${period.day}`;
}

export function periodFromKey(key: string, now = new Date()): ViewPeriod {
  if (key === "today") return todayPeriod(now);
  const [preset, day] = key.split("|");
  if (preset === "day" || preset === "week" || preset === "month") {
    return { preset, day: day || localDateKey(now) };
  }
  return todayPeriod(now);
}
