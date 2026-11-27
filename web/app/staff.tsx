"use client";

import { useEffect, useState } from "react";

import {
  api,
  ApiError,
  type Availability,
  type Employee,
  type EmployeeIn,
  type Skill,
  type WeeklyRule,
} from "@/lib/api";
import { describeWindow, formatDate, hhmm, LONG_HOURS, showTime, WEEKDAYS } from "@/lib/dates";

/** The Staff tab: who works here, their roles, hours and availability. */
export function StaffPage({ restaurantId }: { restaurantId: number }) {
  const [staff, setStaff] = useState<Employee[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [showLeavers, setShowLeavers] = useState(false);
  // null = nothing open, "new" = the add form, a number = that person.
  const [open, setOpen] = useState<number | "new" | null>(null);
  const [reloads, setReloads] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.employees(restaurantId, showLeavers), api.skills(restaurantId)])
      .then(([people, roles]) => {
        if (cancelled) return;
        setStaff(people);
        setSkills(roles);
      })
      .catch((e: ApiError) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [restaurantId, showLeavers, reloads]);

  const reload = () => setReloads((n) => n + 1);
  const person = typeof open === "number" ? staff.find((e) => e.id === open) : undefined;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <section>
        <div className="mb-3 flex items-center gap-3 text-sm">
          <h2 className="text-lg font-semibold">Staff ({staff.length})</h2>
          <label className="ml-auto flex items-center gap-2 text-slate-600">
            <input
              type="checkbox"
              checked={showLeavers}
              onChange={(e) => setShowLeavers(e.target.checked)}
            />
            Show people who left
          </label>
          <button className={primary} onClick={() => setOpen("new")}>
            + Add person
          </button>
        </div>

        {error && (
          <p className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>
        )}

        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left text-slate-600">
              <tr>
                <th className="p-2 font-medium">Name</th>
                <th className="p-2 font-medium">Roles</th>
                <th className="p-2 text-right font-medium">Hours</th>
              </tr>
            </thead>
            <tbody>
              {staff.map((e) => (
                <tr
                  key={e.id}
                  className={`cursor-pointer border-t border-slate-100 hover:bg-amber-50 ${
                    open === e.id ? "bg-amber-100" : ""
                  } ${e.status === "inactive" ? "text-slate-400" : ""}`}
                  onClick={() => setOpen(e.id)}
                >
                  <td className="p-2 font-medium">
                    {e.display_name}
                    {e.status === "inactive" && <span className="ml-2 text-xs">(left)</span>}
                  </td>
                  <td className="p-2">
                    {e.skills.join(", ") || <em className="text-slate-400">none</em>}
                  </td>
                  <td className="p-2 text-right tabular-nums" title="Target / most hours a week">
                    {e.target_hours !== null ? `${e.target_hours} / ` : ""}
                    {e.max_hours} h
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        {open === "new" && (
          <PersonForm
            key="new"
            restaurantId={restaurantId}
            skills={skills}
            onSkillAdded={reload}
            onSaved={(saved) => {
              reload();
              setOpen(saved.id);
            }}
            onClose={() => setOpen(null)}
          />
        )}
        {person && (
          <div className="space-y-4">
            <PersonForm
              key={person.id}
              restaurantId={restaurantId}
              skills={skills}
              person={person}
              onSkillAdded={reload}
              onSaved={(saved) => {
                if (saved.status === "inactive") setShowLeavers(true); // keep them on screen
                reload();
              }}
              onClose={() => setOpen(null)}
            />
            <AvailabilityEditor
              key={`a-${person.id}`}
              restaurantId={restaurantId}
              person={person}
            />
          </div>
        )}
        {open === null && (
          <p className="rounded-lg border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">
            Click someone to edit them, or add a new person.
          </p>
        )}
      </section>
    </div>
  );
}

// Details and roles

function PersonForm({
  restaurantId,
  skills,
  person,
  onSkillAdded,
  onSaved,
  onClose,
}: {
  restaurantId: number;
  skills: Skill[];
  person?: Employee;
  onSkillAdded: () => void;
  onSaved: (saved: Employee) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState({
    display_name: person?.display_name ?? "",
    max_hours: String(person?.max_hours ?? 25),
    target_hours: person?.target_hours === null || !person ? "" : String(person.target_hours),
    skills: person?.skills ?? [],
    employee_number: person?.employee_number ?? "",
    phone: person?.phone ?? "",
  });
  const [newRole, setNewRole] = useState("");
  const [message, setMessage] = useState<{ tone: "red" | "green"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (field: keyof typeof form) => (value: string) => setForm({ ...form, [field]: value });

  function toggleRole(name: string) {
    setForm({
      ...form,
      skills: form.skills.includes(name)
        ? form.skills.filter((s) => s !== name)
        : [...form.skills, name],
    });
  }

  async function addRole() {
    if (!newRole.trim()) return;
    try {
      const role = await api.addSkill(restaurantId, newRole);
      setForm({ ...form, skills: [...form.skills, role.name] });
      setNewRole("");
      onSkillAdded();
    } catch (e) {
      setMessage({ tone: "red", text: (e as ApiError).message });
    }
  }

  async function save() {
    const body: EmployeeIn = {
      display_name: form.display_name,
      max_hours: Number(form.max_hours),
      target_hours: form.target_hours === "" ? null : Number(form.target_hours),
      skills: form.skills,
      employee_number: form.employee_number || null,
      phone: form.phone || null,
    };
    setSaving(true);
    setMessage(null);
    try {
      const saved = person
        ? await api.updateEmployee(restaurantId, person.id, body)
        : await api.addEmployee(restaurantId, body);
      setMessage({
        tone: "green",
        text: person
          ? "Saved."
          : "Added. Now give them weekly hours; without hours they can't be scheduled.",
      });
      onSaved(saved);
    } catch (e) {
      setMessage({ tone: "red", text: (e as ApiError).message });
    } finally {
      setSaving(false);
    }
  }

  async function setStatus(status: Employee["status"]) {
    if (!person) return;
    setSaving(true);
    try {
      const saved = await api.updateEmployee(restaurantId, person.id, { status });
      setMessage({
        tone: "green",
        text:
          status === "inactive"
            ? "Marked as left. Update the schedule to take them off any published shifts."
            : "Welcome back. They can be scheduled again.",
      });
      onSaved(saved);
    } catch (e) {
      setMessage({ tone: "red", text: (e as ApiError).message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={card}>
      <div className="mb-3 flex items-center">
        <h2 className="text-lg font-semibold">{person ? person.display_name : "Add a person"}</h2>
        <button className="ml-auto text-sm text-slate-500 hover:underline" onClick={onClose}>
          Close
        </button>
      </div>

      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <Field label="Name">
          <input
            className={input}
            value={form.display_name}
            onChange={(e) => set("display_name")(e.target.value)}
          />
        </Field>
        <Field label="Phone (optional)">
          <input
            className={input}
            value={form.phone}
            onChange={(e) => set("phone")(e.target.value)}
          />
        </Field>
        <Field label="Most hours a week">
          <input
            className={input}
            type="number"
            min={0}
            max={80}
            step={1}
            value={form.max_hours}
            onChange={(e) => set("max_hours")(e.target.value)}
          />
        </Field>
        <Field label="Hours they'd like (optional)">
          <input
            className={input}
            type="number"
            min={0}
            max={80}
            step={0.5}
            value={form.target_hours}
            onChange={(e) => set("target_hours")(e.target.value)}
          />
        </Field>
        <Field label="Employee number (optional)">
          <input
            className={input}
            value={form.employee_number}
            onChange={(e) => set("employee_number")(e.target.value)}
          />
        </Field>
      </div>

      <div className="mt-4 text-sm">
        <div className="mb-1 text-slate-600">Roles</div>
        <div className="flex flex-wrap gap-2">
          {skills.map((skill) => (
            <label
              key={skill.id}
              className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 ${
                form.skills.includes(skill.name)
                  ? "border-amber-500 bg-amber-100"
                  : "border-slate-300 bg-white"
              }`}
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={form.skills.includes(skill.name)}
                onChange={() => toggleRole(skill.name)}
              />
              {skill.name}
            </label>
          ))}
          <span className="flex items-center gap-1">
            <input
              className={`${input} w-32`}
              placeholder="New role"
              value={newRole}
              onChange={(e) => setNewRole(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addRole()}
            />
            <button className={secondary} onClick={addRole}>
              Add
            </button>
          </span>
        </div>
      </div>

      {message && <Message {...message} />}

      <div className="mt-4 flex items-center gap-2">
        <button className={primary} disabled={saving} onClick={save}>
          {person ? "Save" : "Add person"}
        </button>
        {person?.status === "active" && (
          <button
            className={`${secondary} ml-auto`}
            disabled={saving}
            onClick={() => setStatus("inactive")}
          >
            Mark as left
          </button>
        )}
        {person?.status === "inactive" && (
          <button
            className={`${secondary} ml-auto`}
            disabled={saving}
            onClick={() => setStatus("active")}
          >
            Bring back
          </button>
        )}
      </div>
    </div>
  );
}

// Weekly hours and days off

function AvailabilityEditor({ restaurantId, person }: { restaurantId: number; person: Employee }) {
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [rules, setRules] = useState<WeeklyRule[]>([]);
  const [message, setMessage] = useState<{ tone: "red" | "green"; text: string } | null>(null);

  useEffect(() => {
    api
      .availability(restaurantId, person.id)
      .then((a) => {
        setAvailability(a);
        setRules(a.weekly.map(trimRule));
      })
      .catch((e: ApiError) => setMessage({ tone: "red", text: e.message }));
  }, [restaurantId, person.id]);

  function changeRule(index: number, change: Partial<WeeklyRule>) {
    setMessage(null);
    setRules(rules.map((rule, i) => (i === index ? { ...rule, ...change } : rule)));
  }

  async function saveWeekly() {
    setMessage(null);
    if (rules.some((r) => !r.start_time || !r.end_time)) {
      setMessage({ tone: "red", text: "Fill in both times on every row, or remove the row." });
      return;
    }
    try {
      const saved = await api.setWeekly(restaurantId, person.id, rules);
      setAvailability(saved);
      setRules(saved.weekly.map(trimRule));
      setMessage({ tone: "green", text: "Weekly hours saved. Update the schedule to use them." });
    } catch (e) {
      setMessage({ tone: "red", text: (e as ApiError).message });
    }
  }

  if (!availability) return null;

  return (
    <div className={card}>
      <h3 className="mb-1 font-semibold">Weekly hours</h3>
      <p className="mb-3 text-xs text-slate-500">
        When {person.display_name} can work, every week. An end earlier than the start runs past
        midnight (16:00 to 02:00).
      </p>

      {rules.length === 0 && (
        <p className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
          No hours yet, so {person.display_name} can&apos;t be scheduled.
        </p>
      )}

      <div className="space-y-2 text-sm">
        {rules.map((rule, index) => (
          <div key={index}>
            <div className="flex items-center gap-2">
              <select
                className={`${input} w-36`}
                value={rule.weekday}
                onChange={(e) => changeRule(index, { weekday: Number(e.target.value) })}
              >
                {WEEKDAYS.map((day, i) => (
                  <option key={day} value={i}>
                    {day}
                  </option>
                ))}
              </select>
              <input
                className={`${input} w-28`}
                type="time"
                value={rule.start_time}
                onChange={(e) => changeRule(index, { start_time: e.target.value })}
              />
              <span>to</span>
              <input
                className={`${input} w-28`}
                type="time"
                value={rule.end_time}
                onChange={(e) => changeRule(index, { end_time: e.target.value })}
              />
              <button
                className="px-2 text-slate-400 hover:text-red-600"
                aria-label="Remove these hours"
                onClick={() => setRules(rules.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </div>
            <WindowNote start={rule.start_time} end={rule.end_time} weekday={rule.weekday} />
          </div>
        ))}
      </div>

      <div className="mt-3 flex gap-2">
        <button
          className={secondary}
          onClick={() =>
            setRules([...rules, { weekday: nextDay(rules), start_time: "", end_time: "" }])
          }
        >
          + Add hours
        </button>
        <button className={primary} onClick={saveWeekly}>
          Save weekly hours
        </button>
      </div>

      {message && <Message {...message} />}

      <DaysOff
        restaurantId={restaurantId}
        person={person}
        availability={availability}
        onChange={setAvailability}
      />
    </div>
  );
}

function DaysOff({
  restaurantId,
  person,
  availability,
  onChange,
}: {
  restaurantId: number;
  person: Employee;
  availability: Availability;
  onChange: (a: Availability) => void;
}) {
  const [date, setDate] = useState("");
  const [allDay, setAllDay] = useState(true);
  const [from, setFrom] = useState("10:00");
  const [to, setTo] = useState("16:00");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function add() {
    setError(null);
    if (!date) {
      setError("Pick a date.");
      return;
    }
    try {
      onChange(
        await api.setException(restaurantId, person.id, date, {
          available: !allDay,
          intervals: allDay ? [] : [{ start_time: from, end_time: to }],
          note: note || null,
        }),
      );
      setDate("");
      setNote("");
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function remove(day: string) {
    setError(null);
    try {
      await api.removeException(restaurantId, person.id, day);
      onChange({
        ...availability,
        exceptions: availability.exceptions.filter((x) => x.date !== day),
      });
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  return (
    <div className="mt-6 border-t border-slate-200 pt-4">
      <h3 className="mb-1 font-semibold">Days off and changed hours</h3>
      <p className="mb-3 text-xs text-slate-500">These replace the weekly hours on that date.</p>

      {availability.exceptions.length > 0 && (
        <ul className="mb-3 space-y-1 text-sm">
          {availability.exceptions.map((x) => (
            <li key={x.date} className="flex items-center gap-2">
              <span className="w-28 font-medium">{formatDate(x.date)}</span>
              <span className="grow">
                {x.available
                  ? `Only ${x.intervals.map((i) => `${showTime(i.start_time)}–${showTime(i.end_time)}`).join(", ")}`
                  : "Off all day"}
                {x.note && <span className="text-slate-500"> · {x.note}</span>}
              </span>
              <button
                className="text-xs text-slate-500 hover:text-red-600 hover:underline"
                onClick={() => remove(x.date)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <input
          className={`${input} w-40`}
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          aria-label="Date"
        />
        <select
          className={`${input} w-40`}
          value={allDay ? "off" : "some"}
          onChange={(e) => setAllDay(e.target.value === "off")}
        >
          <option value="off">Off all day</option>
          <option value="some">Only these hours</option>
        </select>
        {!allDay && (
          <>
            <input
              className={`${input} w-28`}
              type="time"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
            <span>to</span>
            <input
              className={`${input} w-28`}
              type="time"
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </>
        )}
        <input
          className={`${input} w-40`}
          placeholder="Note (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button className={secondary} onClick={add}>
          Add
        </button>
      </div>
      {error && <Message tone="red" text={error} />}
    </div>
  );
}

// Small pieces

/** "Tue 06:00 → 15:00 · 9 h" under a row, in amber when it looks like an AM/PM slip. */
function WindowNote({ start, end, weekday }: { start: string; end: string; weekday: number }) {
  const window = describeWindow(start, end, weekday);
  if (!window) return null;
  const suspicious = window.hours === 0 || window.hours > LONG_HOURS;
  return (
    <p className={`mt-0.5 pl-1 text-xs ${suspicious ? "text-amber-700" : "text-slate-500"}`}>
      {window.text}
      {window.overnight && !suspicious && " (overnight)"}
      {window.hours > LONG_HOURS && ". That's a long time: check AM and PM."}
    </p>
  );
}

function trimRule(rule: WeeklyRule): WeeklyRule {
  return { ...rule, start_time: hhmm(rule.start_time), end_time: hhmm(rule.end_time) };
}

/** The first weekday with no hours yet, so "+ Add hours" doesn't repeat Monday. */
function nextDay(rules: WeeklyRule[]): number {
  const used = new Set(rules.map((r) => r.weekday));
  return [0, 1, 2, 3, 4, 5, 6].find((d) => !used.has(d)) ?? 0;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-slate-600">{label}</span>
      {children}
    </label>
  );
}

function Message({ tone, text }: { tone: "red" | "green"; text: string }) {
  return (
    <p
      className={`mt-3 rounded-md px-3 py-2 text-sm ${
        tone === "red" ? "bg-red-50 text-red-800" : "bg-emerald-50 text-emerald-900"
      }`}
    >
      {text}
    </p>
  );
}

const card = "rounded-lg border border-slate-200 bg-white p-4";
const input = "w-full rounded-md border border-slate-300 bg-white px-2 py-1.5";
const primary =
  "rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50";
const secondary =
  "rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50";
