"use client";

import { useState } from "react";

import { type Template } from "@/lib/api";
import { shiftCount } from "@/lib/dates";

/** "Get Lotus Kitchen ready": what's left before the first schedule. */
export function Checklist({
  name,
  staffCount,
  shiftCount,
  published,
  onAddStaff,
}: {
  name: string;
  staffCount: number;
  shiftCount: number;
  published: boolean;
  onAddStaff: () => void;
}) {
  const steps = [
    { done: true, text: "Name, timezone and roles" },
    {
      done: staffCount > 0,
      text: "Add your staff and when they can work",
      action: { label: "Add staff", onClick: onAddStaff },
    },
    { done: shiftCount > 0, text: "Add the shifts you run and who they need" },
    { done: published, text: "Create and publish your first schedule" },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  const next = steps.findIndex((s) => !s.done);
  if (next === -1) return null;

  return (
    <div className="mb-4 rounded-lg border border-sky-300 bg-sky-50 p-4 text-sm">
      <h2 className="mb-2 font-semibold text-sky-900">
        Get {name} ready · {doneCount} of {steps.length} done
      </h2>
      <ol className="space-y-1.5">
        {steps.map((step, i) => (
          <li key={step.text} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className={`flex h-5 w-5 items-center justify-center rounded-full border text-xs ${
                step.done
                  ? "border-emerald-600 bg-emerald-600 text-white"
                  : i === next
                    ? "border-sky-700 text-sky-700"
                    : "border-slate-300 text-slate-400"
              }`}
            >
              {step.done ? "✓" : i + 1}
            </span>
            <span
              className={`grow ${
                step.done ? "text-slate-500 line-through" : i === next ? "" : "text-slate-500"
              }`}
            >
              {step.text}
              <span className="sr-only">{step.done ? " (done)" : ""}</span>
            </span>
            {i === next && step.action && (
              <button
                className="rounded-md border border-sky-700 px-2 py-0.5 text-xs text-sky-800 hover:bg-sky-100"
                onClick={step.action.onClick}
              >
                {step.action.label}
              </button>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** A week with no shifts: start it by hand, from last week, or from a template. */
export function EmptyWeek({
  lastWeekShifts,
  templates,
  onAdd,
  onCopyLastWeek,
  onUseTemplate,
  onDeleteTemplate,
}: {
  lastWeekShifts: number;
  templates: Template[];
  onAdd: () => void;
  onCopyLastWeek: () => void;
  onUseTemplate: (template: Template) => void;
  onDeleteTemplate: (template: Template) => void;
}) {
  const [picked, setPicked] = useState<number | "">("");
  const template = templates.find((t) => t.id === picked);

  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-10 text-center text-sm">
      <h2 className="text-base font-semibold">No shifts this week</h2>
      <p className="mx-auto mb-5 mt-1 max-w-md text-slate-500">
        Shifts say what you need, like &quot;Lunch 11:00 AM to 3:00 PM, 2 cooks and 1 server&quot;.
        ShiftSense then picks who works them.
      </p>

      <div className="mx-auto grid max-w-2xl gap-3 sm:grid-cols-3">
        <div className={choice}>
          <div className="font-medium">Build by hand</div>
          <p className="text-xs text-slate-500">Add shifts one at a time</p>
          <button className={primary} onClick={onAdd}>
            + Add shift
          </button>
        </div>

        <div className={choice}>
          <div className="font-medium">Copy last week</div>
          <p className="text-xs text-slate-500">
            {lastWeekShifts > 0
              ? `${shiftCount(lastWeekShifts)}, same days and times`
              : "Last week has no shifts to copy"}
          </p>
          <button className={secondary} disabled={lastWeekShifts === 0} onClick={onCopyLastWeek}>
            Copy shifts
          </button>
        </div>

        <div className={choice}>
          <div className="font-medium">Use a template</div>
          {templates.length === 0 ? (
            <p className="text-xs text-slate-500">
              None yet. Save a finished week as a template to reuse it.
            </p>
          ) : (
            <select
              className="w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-xs"
              value={picked}
              onChange={(e) => setPicked(e.target.value === "" ? "" : Number(e.target.value))}
              aria-label="Template"
            >
              <option value="">Pick a template…</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({shiftCount(t.shift_count)})
                </option>
              ))}
            </select>
          )}
          <div className="flex items-center justify-center gap-2">
            <button
              className={secondary}
              disabled={!template}
              onClick={() => template && onUseTemplate(template)}
            >
              Use template
            </button>
            {template && (
              <button
                className="text-xs text-slate-500 hover:text-red-600 hover:underline"
                onClick={() => {
                  onDeleteTemplate(template);
                  setPicked("");
                }}
              >
                Delete
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Save the current week's shifts as a template. */
export function SaveTemplate({
  onSave,
  onCancel,
}: {
  onSave: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  function save() {
    if (!name.trim()) {
      setError("Give the template a name, like Normal week.");
      return;
    }
    onSave(name);
  }

  return (
    <span className="flex flex-wrap items-center gap-2">
      <input
        className="w-44 rounded-md border border-slate-300 bg-white px-2 py-1.5"
        placeholder="Normal week"
        value={name}
        autoFocus
        onChange={(e) => {
          setName(e.target.value);
          setError(null);
        }}
        onKeyDown={(e) => e.key === "Enter" && save()}
        aria-label="Template name"
      />
      <button className={secondary} onClick={save}>
        Save template
      </button>
      <button className="text-slate-500 hover:underline" onClick={onCancel}>
        Cancel
      </button>
      {error && <span className="text-xs text-red-700">{error}</span>}
    </span>
  );
}

const choice = "flex flex-col items-center gap-2 rounded-lg border border-slate-200 p-3";
const primary =
  "rounded-md bg-slate-900 px-3 py-1.5 font-medium text-white hover:bg-slate-700 disabled:opacity-50";
const secondary =
  "rounded-md border border-slate-300 bg-white px-3 py-1.5 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50";
