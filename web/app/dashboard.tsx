"use client";

import { useEffect, useState } from "react";

import { api, ApiError, type Restaurant, type Schedule, type Shift } from "@/lib/api";

// The demo restaurant's week. Later this will default to the current week.
const DEMO_WEEK = "2026-11-23";

type WeekData = { shifts: Shift[]; schedule: Schedule | null };

export function Dashboard() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [restaurantId, setRestaurantId] = useState<number | null>(null);
  const [week, setWeek] = useState(DEMO_WEEK);
  const [data, setData] = useState<WeekData | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load the restaurant list once and pick the newest (the latest demo seed).
  useEffect(() => {
    api
      .restaurants()
      .then((list) => {
        setRestaurants(list);
        if (list.length > 0) setRestaurantId(list[list.length - 1].id);
      })
      .catch((e: ApiError) => setError(e.message));
  }, []);

  // Load the week's shifts and published schedule whenever the selection changes.
  useEffect(() => {
    if (restaurantId === null) return;
    let cancelled = false;

    Promise.all([
      api.shifts(restaurantId, week),
      api.published(restaurantId, week).catch((e: ApiError) => {
        if (e.code === "not_found") return null; // nothing published yet
        throw e;
      }),
    ])
      .then(([shifts, schedule]) => {
        if (!cancelled) {
          setData({ shifts, schedule });
          setError(null);
        }
      })
      .catch((e: ApiError) => !cancelled && setError(e.message));

    return () => {
      cancelled = true;
    };
  }, [restaurantId, week]);

  const restaurant = restaurants.find((r) => r.id === restaurantId);

  return (
    <main className="mx-auto max-w-7xl p-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">ShiftSense</h1>
          <p className="text-sm text-slate-500">
            {restaurant ? `${restaurant.name} · ${restaurant.timezone}` : "Loading…"}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <select
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm"
            value={restaurantId ?? ""}
            onChange={(e) => setRestaurantId(Number(e.target.value))}
            aria-label="Restaurant"
          >
            {restaurants.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name} (#{r.id})
              </option>
            ))}
          </select>

          <div className="flex items-center rounded-md border border-slate-300 bg-white text-sm">
            <button
              className="px-3 py-1.5 hover:bg-slate-100"
              onClick={() => setWeek(addDays(week, -7))}
              aria-label="Previous week"
            >
              ‹
            </button>
            <span className="px-2">Week of {formatDate(week)}</span>
            <button
              className="px-3 py-1.5 hover:bg-slate-100"
              onClick={() => setWeek(addDays(week, 7))}
              aria-label="Next week"
            >
              ›
            </button>
          </div>
        </div>
      </header>

      {error && (
        <p className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {error}
        </p>
      )}

      {data && <WeekView week={week} shifts={data.shifts} schedule={data.schedule} />}
    </main>
  );
}

function WeekView({
  week,
  shifts,
  schedule,
}: {
  week: string;
  shifts: Shift[];
  schedule: Schedule | null;
}) {
  if (shifts.length === 0) {
    return <EmptyState text="No shifts this week." />;
  }

  const days = Array.from({ length: 7 }, (_, i) => addDays(week, i));
  const slots = uniqueSlots(shifts);
  const missing = schedule?.shortages.reduce((total, s) => total + s.missing, 0) ?? 0;

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        {schedule ? (
          <>
            <Badge tone="green">Published · revision {schedule.revision_number}</Badge>
            {missing > 0 ? (
              <Badge tone="amber">{missing} position(s) short</Badge>
            ) : (
              <Badge tone="green">Fully covered</Badge>
            )}
            <span className="text-slate-500">{schedule.assignments.length} assignments</span>
          </>
        ) : (
          <Badge tone="slate">Nothing published for this week yet</Badge>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full min-w-[900px] table-fixed border-collapse text-sm">
          <thead>
            <tr className="bg-slate-100 text-left">
              <th className="w-28 p-2 font-medium text-slate-600">Shift</th>
              {days.map((day) => (
                <th key={day} className="p-2 font-medium text-slate-600">
                  {formatDay(day)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slots.map((slot) => (
              <tr key={slot.key} className="border-t border-slate-200 align-top">
                <td className="p-2">
                  <div className="font-medium">{slot.name}</div>
                  <div className="text-xs text-slate-500">
                    {slot.start}–{slot.end}
                  </div>
                </td>
                {days.map((day) => {
                  const shift = shifts.find(
                    (s) => s.local_date === day && slotKey(s) === slot.key,
                  );
                  return (
                    <td key={day} className="border-l border-slate-100 p-2">
                      {shift && <ShiftCell shift={shift} schedule={schedule} />}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ShiftCell({ shift, schedule }: { shift: Shift; schedule: Schedule | null }) {
  return (
    <div className="space-y-2">
      {shift.requirements.map((requirement) => {
        const people =
          schedule?.assignments.filter(
            (a) => a.shift_id === shift.id && a.role === requirement.role,
          ) ?? [];
        const short = schedule?.shortages.find(
          (s) => s.shift_id === shift.id && s.role === requirement.role,
        );

        return (
          <div key={requirement.role}>
            <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-slate-500">
              <span>
                {requirement.role} {people.length}/{requirement.count}
              </span>
              {short && <span className="text-amber-700">−{short.missing}</span>}
            </div>
            <ul>
              {people.map((person) => (
                <li key={person.employee_id} className="truncate">
                  {person.employee_name}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function Badge({ tone, children }: { tone: "green" | "amber" | "slate"; children: React.ReactNode }) {
  const colours = {
    green: "bg-emerald-50 text-emerald-800 border-emerald-200",
    amber: "bg-amber-50 text-amber-800 border-amber-200",
    slate: "bg-slate-100 text-slate-700 border-slate-200",
  };
  return <span className={`rounded-full border px-2.5 py-0.5 ${colours[tone]}`}>{children}</span>;
}

function EmptyState({ text }: { text: string }) {
  return (
    <p className="rounded-lg border border-dashed border-slate-300 p-10 text-center text-slate-500">
      {text}
    </p>
  );
}

// Helpers

type Slot = { key: string; name: string; start: string; end: string };

function slotKey(shift: Shift): string {
  return `${shift.local_start}-${shift.local_end}`;
}

/** The distinct shift times in the week (lunch, dinner, late close), earliest first. */
function uniqueSlots(shifts: Shift[]): Slot[] {
  const slots = new Map<string, Slot>();
  for (const shift of shifts) {
    const key = slotKey(shift);
    if (!slots.has(key)) {
      const start = shift.local_start.slice(0, 5);
      slots.set(key, {
        key,
        name: shift.label ?? slotName(start),
        start,
        end: shift.local_end.slice(0, 5),
      });
    }
  }
  return [...slots.values()].sort((a, b) => a.start.localeCompare(b.start));
}

function slotName(start: string): string {
  const hour = Number(start.slice(0, 2));
  if (hour < 15) return "Lunch";
  if (hour < 22) return "Dinner";
  return "Late close";
}

// Dates are plain "YYYY-MM-DD" strings; UTC avoids the browser's timezone.
function addDays(isoDate: string, days: number): string {
  const date = new Date(`${isoDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function formatDate(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

function formatDay(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}
