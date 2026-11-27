"use client";

import { useState } from "react";

import { api, ApiError, type Restaurant } from "@/lib/api";

type Start = "blank" | "demo";

/** First step for a new restaurant: its name, timezone and roles, or a demo to try. */
export function SetupScreen({
  onCreated,
  onCancel,
}: {
  onCreated: (restaurant: Restaurant, demo: boolean) => void;
  onCancel?: () => void; // missing when there's no restaurant to go back to
}) {
  const [name, setName] = useState("");
  const [timezone, setTimezone] = useState(browserTimezone);
  const [roles, setRoles] = useState(["cook", "server", "host"]);
  const [newRole, setNewRole] = useState("");
  const [start, setStart] = useState<Start>("blank");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function addRole() {
    const role = newRole.trim().toLowerCase().replace(/\s+/g, " ");
    if (role && !roles.includes(role)) setRoles([...roles, role]);
    setNewRole("");
  }

  async function create() {
    setError(null);
    if (start === "blank" && !name.trim()) {
      setError("Give your restaurant a name.");
      return;
    }
    if (start === "blank" && roles.length === 0) {
      setError("Add at least one role, like cook or server.");
      return;
    }
    setSaving(true);
    try {
      const restaurant =
        start === "demo"
          ? await api.openDemo()
          : await api.createRestaurant({ name, timezone, roles });
      onCreated(restaurant, start === "demo");
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl rounded-lg border border-slate-200 bg-white p-6">
      <h2 className="text-xl font-semibold">Set up your restaurant</h2>
      <p className="mb-5 text-sm text-slate-500">
        Start with the basics. You&apos;ll add staff and shifts next.
      </p>

      <div className="mb-5 grid gap-2 sm:grid-cols-3">
        <StartCard
          icon="📄"
          title="Start blank"
          text="Add your own staff and shifts"
          selected={start === "blank"}
          onClick={() => setStart("blank")}
        />
        <StartCard
          icon="📷"
          title="Upload a schedule"
          text="Photo, PDF or Excel. Coming soon"
          disabled
        />
        <StartCard
          icon="🧪"
          title="Try demo data"
          text="A sample bistro with 25 staff"
          selected={start === "demo"}
          onClick={() => setStart("demo")}
        />
      </div>

      {start === "blank" && (
        <div className="space-y-4 text-sm">
          <label className="block">
            <span className="mb-1 block text-slate-600">Restaurant name</span>
            <input
              className={input}
              placeholder="Lotus Kitchen"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setError(null);
              }}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-slate-600">Timezone</span>
            <select
              className={input}
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
            >
              {timezones().map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>
          </label>
          <div>
            <span className="mb-1 block text-slate-600">Roles in your restaurant</span>
            <div className="flex flex-wrap items-center gap-2">
              {roles.map((role) => (
                <span
                  key={role}
                  className="flex items-center gap-1 rounded-full border border-amber-500 bg-amber-100 py-1 pl-3 pr-2"
                >
                  {role}
                  <button
                    className="px-1 text-amber-700 hover:text-red-600"
                    aria-label={`Remove ${role}`}
                    onClick={() => setRoles(roles.filter((r) => r !== role))}
                  >
                    ×
                  </button>
                </span>
              ))}
              <input
                className="w-32 rounded-md border border-slate-300 bg-white px-2 py-1.5"
                placeholder="bartender"
                value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addRole()}
                aria-label="New role"
              />
              <button className={secondary} onClick={addRole}>
                Add role
              </button>
            </div>
          </div>
        </div>
      )}

      {start === "demo" && (
        <p className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">
          Creates &quot;Demo Bistro&quot; with made-up staff, hours and a week of shifts (week of 23
          Nov 2026), so you can try call-outs and repairs straight away.
        </p>
      )}

      {error && <p className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}

      <div className="mt-6 flex items-center gap-3">
        <button
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          disabled={saving}
          onClick={create}
        >
          {start === "demo" ? "Create demo restaurant" : "Create restaurant"}
        </button>
        {onCancel && (
          <button className="text-sm text-slate-500 hover:underline" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

function StartCard({
  icon,
  title,
  text,
  selected = false,
  disabled = false,
  onClick,
}: {
  icon: string;
  title: string;
  text: string;
  selected?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      className={`rounded-lg border p-3 text-left text-sm ${
        selected ? "border-2 border-sky-600 bg-sky-50" : "border-slate-200 bg-white"
      } ${disabled ? "cursor-not-allowed opacity-50" : "hover:border-slate-400"}`}
      disabled={disabled}
      onClick={onClick}
      aria-pressed={selected}
    >
      <div aria-hidden="true">{icon}</div>
      <div className="mt-1 font-medium">{title}</div>
      <div className="text-xs text-slate-500">{text}</div>
    </button>
  );
}

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** Every IANA timezone the browser knows, falling back to a few common ones. */
function timezones(): string[] {
  let zones: string[];
  try {
    zones = Intl.supportedValuesOf("timeZone");
  } catch {
    zones = ["Asia/Colombo", "Europe/London", "America/New_York"];
  }
  // The browser's own zone first, so the default is always in the list.
  return [...new Set([browserTimezone(), "UTC", ...zones])];
}

const input = "w-full rounded-md border border-slate-300 bg-white px-2 py-1.5";
const secondary = "rounded-md border border-slate-300 bg-white px-3 py-1.5 hover:bg-slate-100";
