// Dates are plain "YYYY-MM-DD" strings; UTC avoids the browser's timezone.
export function addDays(isoDate: string, days: number): string {
  const date = new Date(`${isoDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function formatDate(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function formatDay(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

/** "17:00:00" or "17:00" -> "17:00". */
export function hhmm(time: string): string {
  return time.slice(0, 5);
}

export const SHORT_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Longer than this and a time window is probably an AM/PM slip. */
export const LONG_HOURS = 16;

/**
 * How a start and end time read in plain words, e.g. "Tue 16:00 → Wed 15:00 · 23 h".
 * An end earlier than the start is the next day. Returns null until both are filled in.
 */
export function describeWindow(
  start: string,
  end: string,
  weekday: number | null = null,
): { text: string; hours: number; overnight: boolean } | null {
  if (!start || !end) return null;
  const minutes = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
  const length = (minutes(end) - minutes(start) + 1440) % 1440;
  if (length === 0) return { text: "Start and end are the same", hours: 0, overnight: false };

  const overnight = minutes(end) < minutes(start);
  const day = weekday === null ? "" : `${SHORT_DAYS[weekday]} `;
  const endDay = !overnight
    ? ""
    : weekday === null
      ? "next day "
      : `${SHORT_DAYS[(weekday + 1) % 7]} `;
  const hours = Math.round((length / 60) * 10) / 10;
  return {
    text: `${day}${hhmm(start)} → ${endDay}${hhmm(end)} · ${hours} h`,
    hours,
    overnight,
  };
}
