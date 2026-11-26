"use client";

import { useEffect, useState } from "react";

import {
  api,
  ApiError,
  type Assignment,
  type CalloutRisk,
  type Restaurant,
  type RiskReport,
  type Schedule,
  type Shift,
} from "@/lib/api";

// The demo restaurant's week. Later this will default to the current week.
const DEMO_WEEK = "2026-11-23";

type WeekData = { shifts: Shift[]; schedule: Schedule | null };

/** Someone the manager clicked, before confirming the call-out. */
type Selection = { assignment: Assignment; shift: Shift };

/** A repair waiting for the manager's approval. */
type Proposal = { draft: Schedule; calledOut: Selection };

/** Call-out risk per assignment, keyed by `${shift_id}-${employee_id}`. */
type RiskLookup = Map<string, CalloutRisk>;

export function Dashboard() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [restaurantId, setRestaurantId] = useState<number | null>(null);
  const [week, setWeek] = useState(DEMO_WEEK);
  const [data, setData] = useState<WeekData | null>(null);
  const [reloads, setReloads] = useState(0);

  const [selection, setSelection] = useState<Selection | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [risk, setRisk] = useState<RiskReport | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

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

  // Load the week's shifts and published schedule when the selection changes.
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
        if (!cancelled) setData({ shifts, schedule });
      })
      .catch((e: ApiError) => !cancelled && setError(e.message));

    return () => {
      cancelled = true;
    };
  }, [restaurantId, week, reloads]);

  function changeView(update: () => void) {
    update();
    setSelection(null);
    setProposal(null);
    setRisk(null);
    setError(null);
    setNotice(null);
  }

  /** Simulate a call-out for every assignment and mark the risky ones. */
  async function checkRisk() {
    if (restaurantId === null) return;
    setBusy("Simulating a call-out for every shift…");
    setError(null);
    setNotice(null);
    try {
      setRisk(await api.risk(restaurantId, week));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  /** Record the call-out, then ask the engine for the smallest repair. */
  async function callOut(restOfDay: boolean) {
    if (!selection || restaurantId === null) return;
    setBusy("Finding cover…");
    setError(null);
    setNotice(null);
    setRisk(null);
    try {
      await api.callOut(restaurantId, {
        shift_id: selection.shift.id,
        employee_id: selection.assignment.employee_id,
        rest_of_day: restOfDay,
      });
      const result = await api.repair(restaurantId, week);
      if (result.schedule === null) {
        setError(
          `No repair possible (${result.status}). The call-out is recorded, but ` +
            "the shift can't be covered without breaking a rule.",
        );
      } else {
        setProposal({ draft: result.schedule, calledOut: selection });
      }
      setSelection(null);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function approve(acceptShortages: boolean) {
    if (!proposal || restaurantId === null) return;
    setBusy("Publishing…");
    setError(null);
    try {
      const published = await api.publish(restaurantId, proposal.draft, acceptShortages);
      setProposal(null);
      setNotice(`Revision ${published.revision_number} is now live.`);
      setReloads((n) => n + 1);
    } catch (e) {
      const err = e as ApiError;
      if (err.code === "stale") {
        setError(`${err.message} The page has been reloaded.`);
        setProposal(null);
        setReloads((n) => n + 1);
      } else {
        setError(err.message);
      }
    } finally {
      setBusy(null);
    }
  }

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
            onChange={(e) => changeView(() => setRestaurantId(Number(e.target.value)))}
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
              onClick={() => changeView(() => setWeek(addDays(week, -7)))}
              aria-label="Previous week"
            >
              ‹
            </button>
            <span className="px-2">Week of {formatDate(week)}</span>
            <button
              className="px-3 py-1.5 hover:bg-slate-100"
              onClick={() => changeView(() => setWeek(addDays(week, 7)))}
              aria-label="Next week"
            >
              ›
            </button>
          </div>
        </div>
      </header>

      {error && <Banner tone="red">{error}</Banner>}
      {notice && <Banner tone="green">{notice}</Banner>}
      {busy && <Banner tone="slate">{busy}</Banner>}

      {risk && !proposal && !busy && <RiskSummary report={risk} onClose={() => setRisk(null)} />}

      {selection && !busy && (
        <CalloutPanel
          selection={selection}
          onConfirm={callOut}
          onCancel={() => setSelection(null)}
        />
      )}

      {proposal && !busy && data?.schedule && (
        <ProposalPanel
          proposal={proposal}
          published={data.schedule}
          shifts={data.shifts}
          onApprove={approve}
          onDiscard={() => setProposal(null)}
        />
      )}

      {data && (
        <WeekView
          week={week}
          shifts={data.shifts}
          published={data.schedule}
          proposal={proposal}
          selection={selection}
          risks={risk && !proposal ? riskLookup(risk) : null}
          onCheckRisk={busy || proposal ? undefined : checkRisk}
          onSelect={busy || proposal ? undefined : setSelection}
        />
      )}
    </main>
  );
}

// Panels

function CalloutPanel({
  selection,
  onConfirm,
  onCancel,
}: {
  selection: Selection;
  onConfirm: (restOfDay: boolean) => void;
  onCancel: () => void;
}) {
  const [restOfDay, setRestOfDay] = useState(true);
  const { assignment, shift } = selection;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm">
      <p className="grow">
        <strong>{assignment.employee_name}</strong> can&apos;t work{" "}
        <strong>{shiftName(shift)}</strong> ({assignment.role})?
      </p>
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={restOfDay}
          onChange={(e) => setRestOfDay(e.target.checked)}
        />
        Off for the rest of the day
      </label>
      <button
        className="rounded-md bg-amber-600 px-3 py-1.5 font-medium text-white hover:bg-amber-700"
        onClick={() => onConfirm(restOfDay)}
      >
        Call out &amp; find cover
      </button>
      <button className="px-2 py-1.5 text-slate-600 hover:underline" onClick={onCancel}>
        Cancel
      </button>
    </div>
  );
}

function ProposalPanel({
  proposal,
  published,
  shifts,
  onApprove,
  onDiscard,
}: {
  proposal: Proposal;
  published: Schedule;
  shifts: Shift[];
  onApprove: (acceptShortages: boolean) => void;
  onDiscard: () => void;
}) {
  const { draft, calledOut } = proposal;
  const missing = totalMissing(draft);
  const [accepted, setAccepted] = useState(false);
  const names = nameLookup(published, draft);
  const changes = draft.changes ?? [];

  return (
    <div className="mb-4 rounded-lg border border-sky-300 bg-sky-50 px-4 py-3 text-sm">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <strong>Repair proposal · revision {draft.revision_number}</strong>
        <Badge tone="slate">
          {changes.length} change{changes.length === 1 ? "" : "s"}
        </Badge>
        {missing > 0 ? (
          <Badge tone="amber">{missing} position(s) short</Badge>
        ) : (
          <Badge tone="green">Fully covered</Badge>
        )}
        <span className="text-slate-500">
          after {calledOut.assignment.employee_name} called out
        </span>
      </div>

      <ul className="mb-3 space-y-0.5">
        {changes.map((change) => {
          const shift = shifts.find((s) => s.id === change.shift_id);
          const name = names.get(change.employee_id) ?? `#${change.employee_id}`;
          const where = shift ? shiftName(shift) : `shift ${change.shift_id}`;
          return (
            <li key={`${change.shift_id}-${change.employee_id}`}>
              {change.after_role === null ? (
                <span className="text-red-700">
                  − {name} off {where} ({change.before_role})
                </span>
              ) : change.before_role === null ? (
                <span className="text-emerald-700">
                  + {name} on {where} ({change.after_role})
                </span>
              ) : (
                <span className="text-sky-800">
                  ~ {name} on {where}: {change.before_role} → {change.after_role}
                </span>
              )}
            </li>
          );
        })}
      </ul>

      <div className="flex flex-wrap items-center gap-4">
        {missing > 0 && (
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
            />
            Publish with {missing} position(s) short
          </label>
        )}
        <button
          className="rounded-md bg-emerald-600 px-3 py-1.5 font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          disabled={missing > 0 && !accepted}
          onClick={() => onApprove(missing > 0)}
        >
          Approve &amp; publish
        </button>
        <button className="px-2 py-1.5 text-slate-600 hover:underline" onClick={onDiscard}>
          Discard
        </button>
      </div>
    </div>
  );
}

// The grid

function WeekView({
  week,
  shifts,
  published,
  proposal,
  selection,
  risks,
  onCheckRisk,
  onSelect,
}: {
  week: string;
  shifts: Shift[];
  published: Schedule | null;
  proposal: Proposal | null;
  selection: Selection | null;
  risks: RiskLookup | null;
  onCheckRisk?: () => void;
  onSelect?: (selection: Selection) => void;
}) {
  if (shifts.length === 0) {
    return <EmptyState text="No shifts this week." />;
  }

  const shown = proposal?.draft ?? published;
  const names = published ? nameLookup(published, ...(proposal ? [proposal.draft] : [])) : null;
  const days = Array.from({ length: 7 }, (_, i) => addDays(week, i));
  const slots = uniqueSlots(shifts);

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        {published ? (
          <>
            <Badge tone="green">Published · revision {published.revision_number}</Badge>
            {totalMissing(published) > 0 ? (
              <Badge tone="amber">{totalMissing(published)} position(s) short</Badge>
            ) : (
              <Badge tone="green">Fully covered</Badge>
            )}
            <span className="text-slate-500">
              {proposal ? "Showing the proposed repair" : "Click a name to record a call-out"}
            </span>
            {onCheckRisk && (
              <button
                className="ml-auto rounded-md border border-slate-300 bg-white px-3 py-1 hover:bg-slate-100"
                onClick={onCheckRisk}
              >
                Check call-out risk
              </button>
            )}
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
                      {shift && (
                        <ShiftCell
                          shift={shift}
                          schedule={shown}
                          proposal={proposal}
                          names={names}
                          selection={selection}
                          risks={risks}
                          onSelect={onSelect}
                        />
                      )}
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

function ShiftCell({
  shift,
  schedule,
  proposal,
  names,
  selection,
  risks,
  onSelect,
}: {
  shift: Shift;
  schedule: Schedule | null;
  proposal: Proposal | null;
  names: Map<number, string> | null;
  selection: Selection | null;
  risks: RiskLookup | null;
  onSelect?: (selection: Selection) => void;
}) {
  const changes = proposal?.draft.changes ?? [];

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
        const added = new Set(
          changes
            .filter((c) => c.shift_id === shift.id && c.after_role === requirement.role)
            .map((c) => c.employee_id),
        );
        const removed = changes.filter(
          (c) => c.shift_id === shift.id && c.before_role === requirement.role,
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
              {people.map((person) => {
                const isAdded = added.has(person.employee_id);
                const isSelected =
                  selection?.assignment.employee_id === person.employee_id &&
                  selection.shift.id === shift.id;
                const personRisk = risks?.get(`${shift.id}-${person.employee_id}`);
                return (
                  <li key={person.employee_id}>
                    {onSelect ? (
                      <button
                        className={`flex w-full items-center gap-1.5 truncate rounded px-1 text-left hover:bg-amber-100 ${
                          isSelected ? "bg-amber-200" : riskBackground(personRisk)
                        }`}
                        onClick={() => onSelect({ assignment: person, shift })}
                        title={riskTitle(person.employee_name, personRisk)}
                      >
                        {personRisk && personRisk.level !== "covered" && (
                          <span
                            className={`inline-block h-2 w-2 shrink-0 rounded-full ${
                              personRisk.level === "no_fix" ? "bg-red-600" : "bg-amber-500"
                            }`}
                          />
                        )}
                        <span className="truncate">{person.employee_name}</span>
                      </button>
                    ) : (
                      <span
                        className={`block truncate rounded px-1 ${
                          isAdded ? "bg-emerald-100 font-medium text-emerald-900" : ""
                        }`}
                      >
                        {isAdded && "+ "}
                        {person.employee_name}
                      </span>
                    )}
                  </li>
                );
              })}
              {removed.map((change) => (
                <li
                  key={`removed-${change.employee_id}`}
                  className="truncate rounded bg-red-50 px-1 text-red-700 line-through"
                >
                  {names?.get(change.employee_id) ?? `#${change.employee_id}`}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function RiskSummary({ report, onClose }: { report: RiskReport; onClose: () => void }) {
  const count = (level: CalloutRisk["level"]) =>
    report.risks.filter((r) => r.level === level).length;

  if (!report.week_fixable) {
    return (
      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
        <strong>Call-out risk</strong>
        <span>
          A call-out already recorded this week can&apos;t be covered, so no repair is possible
          right now. Find extra staff for that shift first, then check again.
        </span>
        <button className="ml-auto text-red-700 hover:underline" onClick={onClose}>
          Hide
        </button>
      </div>
    );
  }

  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm">
      <strong>Call-out risk</strong>
      <span className="text-slate-600">Simulated {report.checked} call-outs:</span>
      <span className="text-emerald-700">{count("covered")} covered</span>
      <span className="flex items-center gap-1.5 text-amber-700">
        <span className="inline-block h-2 w-2 rounded-full bg-amber-500" />
        {count("short")} leave a position short
      </span>
      <span className="flex items-center gap-1.5 text-red-700">
        <span className="inline-block h-2 w-2 rounded-full bg-red-600" />
        {count("no_fix")} can&apos;t be fixed
      </span>
      <span className="text-slate-500">Hover a name for details.</span>
      <button className="ml-auto text-slate-600 hover:underline" onClick={onClose}>
        Hide
      </button>
    </div>
  );
}

function riskLookup(report: RiskReport): RiskLookup {
  return new Map(report.risks.map((r) => [`${r.shift_id}-${r.employee_id}`, r]));
}

function riskBackground(risk: CalloutRisk | undefined): string {
  if (risk?.level === "no_fix") return "bg-red-50";
  if (risk?.level === "short") return "bg-amber-50";
  return "";
}

function riskTitle(name: string, risk: CalloutRisk | undefined): string {
  if (!risk) return "Record a call-out";
  if (risk.level === "no_fix") {
    return `If ${name} calls out, no repair keeps this week within its minimum staffing.`;
  }
  if (risk.level === "short") {
    return `If ${name} calls out, the best repair leaves ${risk.extra_missing} more position(s) short.`;
  }
  return `If ${name} calls out, it can be covered with ${risk.changes} change(s).`;
}

// Small pieces

function Banner({ tone, children }: { tone: "red" | "green" | "slate"; children: React.ReactNode }) {
  const colours = {
    red: "border-red-200 bg-red-50 text-red-800",
    green: "border-emerald-200 bg-emerald-50 text-emerald-800",
    slate: "border-slate-200 bg-white text-slate-700",
  };
  return <p className={`mb-4 rounded-md border px-4 py-3 text-sm ${colours[tone]}`}>{children}</p>;
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

function totalMissing(schedule: Schedule): number {
  return schedule.shortages.reduce((total, s) => total + s.missing, 0);
}

/** Employee names from the schedules, so removed people can still be named. */
function nameLookup(...schedules: Schedule[]): Map<number, string> {
  const names = new Map<number, string>();
  for (const schedule of schedules) {
    for (const a of schedule.assignments) names.set(a.employee_id, a.employee_name);
  }
  return names;
}

function shiftName(shift: Shift): string {
  const start = shift.local_start.slice(0, 5);
  return `${formatDay(shift.local_date)} ${shift.label ?? slotName(start).toLowerCase()}`;
}

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
