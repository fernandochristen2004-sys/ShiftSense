"use client";

import { useEffect, useState } from "react";

import { api, ApiError, type Shift, type ShiftIn, type Skill } from "@/lib/api";
import { addDays, formatDay, hhmm } from "@/lib/dates";

type Need = { role: string; count: string; min_count: string };

/** Add a shift to the week, or change or remove one. */
export function ShiftEditor({
  restaurantId,
  week,
  shift,
  onSaved,
  onClose,
}: {
  restaurantId: number;
  week: string;
  shift?: Shift; // missing = adding a new one
  onSaved: (message: string) => void;
  onClose: () => void;
}) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [form, setForm] = useState({
    local_date: shift?.local_date ?? week,
    start_time: shift ? hhmm(shift.local_start) : "07:00",
    end_time: shift ? hhmm(shift.local_end) : "11:00",
    label: shift?.label ?? "",
  });
  const [needs, setNeeds] = useState<Need[]>(
    shift
      ? shift.requirements.map((r) => ({
          role: r.role,
          count: String(r.count),
          min_count: String(r.min_count),
        }))
      : [{ role: "", count: "1", min_count: "1" }],
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .skills(restaurantId)
      .then(setSkills)
      .catch((e: ApiError) => setError(e.message));
  }, [restaurantId]);

  const days = Array.from({ length: 7 }, (_, i) => addDays(week, i));

  function changeNeed(index: number, change: Partial<Need>) {
    setNeeds(needs.map((need, i) => (i === index ? { ...need, ...change } : need)));
  }

  function body(): ShiftIn {
    return {
      ...form,
      label: form.label.trim() || null,
      requirements: needs.map((n) => ({
        role: n.role,
        count: Number(n.count),
        min_count: n.min_count === "" ? null : Number(n.min_count),
      })),
    };
  }

  async function run(action: () => Promise<string>) {
    setSaving(true);
    setError(null);
    try {
      onSaved(await action());
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSaving(false);
    }
  }

  const save = () =>
    run(async () => {
      if (shift) {
        // Send only what changed: a published shift can still be renamed.
        const next = body();
        const changes: Partial<ShiftIn> = {};
        if (next.local_date !== shift.local_date) changes.local_date = next.local_date;
        if (next.start_time !== hhmm(shift.local_start)) changes.start_time = next.start_time;
        if (next.end_time !== hhmm(shift.local_end)) changes.end_time = next.end_time;
        if (next.label !== shift.label) changes.label = next.label;
        if (!sameNeeds(next.requirements, shift)) changes.requirements = next.requirements;
        if (Object.keys(changes).length === 0) return "Nothing to change.";
        await api.updateShift(restaurantId, shift.id, changes);
        return changes.label !== undefined && Object.keys(changes).length === 1
          ? "Shift renamed."
          : "Shift changed. Update the schedule to staff it.";
      }
      await api.addShift(restaurantId, body());
      return "Shift added. Update the schedule to staff it.";
    });

  const remove = () =>
    run(async () => {
      if (!shift) return "";
      await api.deleteShift(restaurantId, shift.id);
      return "Shift removed. Update the schedule to take anyone off it.";
    });

  return (
    <div className="mb-4 rounded-lg border border-sky-300 bg-sky-50 p-4 text-sm">
      <div className="mb-3 flex items-center">
        <h2 className="font-semibold">
          {shift
            ? `Edit ${shift.label ?? "shift"} · ${formatDay(shift.local_date)}`
            : "Add a shift"}
        </h2>
        <button className="ml-auto text-slate-500 hover:underline" onClick={onClose}>
          Close
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <Field label="Day">
          <select
            className={input}
            value={form.local_date}
            onChange={(e) => setForm({ ...form, local_date: e.target.value })}
          >
            {days.map((day) => (
              <option key={day} value={day}>
                {formatDay(day)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Starts">
          <input
            className={input}
            type="time"
            value={form.start_time}
            onChange={(e) => setForm({ ...form, start_time: e.target.value })}
          />
        </Field>
        <Field label="Ends">
          <input
            className={input}
            type="time"
            value={form.end_time}
            onChange={(e) => setForm({ ...form, end_time: e.target.value })}
          />
        </Field>
        <Field label="Name (optional)">
          <input
            className={input}
            placeholder="Breakfast"
            value={form.label}
            onChange={(e) => setForm({ ...form, label: e.target.value })}
          />
        </Field>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        An end earlier than the start finishes the next day.
      </p>

      <div className="mt-4">
        <div className="mb-1 text-slate-600">
          People needed <span className="text-xs">(minimum = fewest it can run with)</span>
        </div>
        <div className="space-y-2">
          {needs.map((need, index) => (
            <div key={index} className="flex items-center gap-2">
              <select
                className={`${input} w-40`}
                value={need.role}
                onChange={(e) => changeNeed(index, { role: e.target.value })}
              >
                <option value="">Role…</option>
                {skills.map((s) => (
                  <option key={s.id} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
              <input
                className={`${input} w-20`}
                type="number"
                min={1}
                max={50}
                value={need.count}
                onChange={(e) => changeNeed(index, { count: e.target.value })}
                aria-label="How many"
              />
              <span className="text-xs text-slate-500">minimum</span>
              <input
                className={`${input} w-20`}
                type="number"
                min={0}
                max={50}
                value={need.min_count}
                onChange={(e) => changeNeed(index, { min_count: e.target.value })}
                aria-label="Minimum"
              />
              <button
                className="px-2 text-slate-400 hover:text-red-600"
                aria-label="Remove this role"
                onClick={() => setNeeds(needs.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <button
          className="mt-2 text-sky-800 hover:underline"
          onClick={() => setNeeds([...needs, { role: "", count: "1", min_count: "1" }])}
        >
          + Add a role
        </button>
      </div>

      {error && <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-red-800">{error}</p>}

      <div className="mt-4 flex items-center gap-2">
        <button
          className="rounded-md bg-sky-700 px-3 py-1.5 font-medium text-white hover:bg-sky-800 disabled:opacity-50"
          disabled={saving}
          onClick={save}
        >
          {shift ? "Save shift" : "Add shift"}
        </button>
        {shift && (
          <button
            className="ml-auto rounded-md border border-red-300 bg-white px-3 py-1.5 text-red-700 hover:bg-red-50 disabled:opacity-50"
            disabled={saving}
            onClick={remove}
          >
            Remove shift
          </button>
        )}
      </div>
    </div>
  );
}

function sameNeeds(requirements: ShiftIn["requirements"], shift: Shift): boolean {
  const key = (role: string, count: number, min: number) => `${role}:${count}:${min}`;
  const before = shift.requirements.map((r) => key(r.role, r.count, r.min_count)).sort();
  const after = requirements.map((r) => key(r.role, r.count, r.min_count ?? r.count)).sort();
  return before.join() === after.join();
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-slate-600">{label}</span>
      {children}
    </label>
  );
}

const input = "rounded-md border border-slate-300 bg-white px-2 py-1.5";
