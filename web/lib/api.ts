// Talks to the ShiftSense API. Types mirror api/stored_schemas.py,
// api/staff_schemas.py and api/shift_schemas.py.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Restaurant = { id: number; name: string; timezone: string };

export type Requirement = { role: string; count: number; min_count: number };

export type Shift = {
  id: number;
  label: string | null;
  starts_at: string;
  ends_at: string;
  local_date: string; // "2026-11-23", restaurant time
  local_start: string; // "11:00:00"
  local_end: string;
  requirements: Requirement[];
};

export type Shortage = { shift_id: number; role: string; missing: number };

export type Assignment = {
  shift_id: number;
  role: string;
  employee_id: number;
  employee_name: string;
};

export type Change = {
  shift_id: number;
  employee_id: number;
  before_role: string | null;
  after_role: string | null;
};

export type Schedule = {
  id: number;
  revision_number: number;
  status: "draft" | "published" | "archived";
  row_version: number;
  based_on_id: number | null;
  fully_covered: boolean | null;
  shortages: Shortage[];
  assignment_changes: number | null;
  published_at: string | null;
  assignments: Assignment[];
  changes: Change[] | null;
};

/** An error from the API, with the code the backend sends (not_found, stale, ...). */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(API_URL + path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "offline", `Can't reach the API at ${API_URL}. Is uvicorn running?`);
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    if (detail && typeof detail === "object" && "code" in detail) {
      throw new ApiError(response.status, detail.code, detail.message);
    }
    throw new ApiError(response.status, "error", `Request failed (${response.status}).`);
  }
  if (response.status === 204) return undefined as T; // no content
  return response.json() as Promise<T>;
}

/** Why a call-out can't be covered: one entry per gap nobody can fill. */
export type Explanation = {
  summary: string;
  together_only: boolean; // everyone's free on their own, just not all at once
  gaps: {
    shift_id: number;
    role: string;
    called_out: { employee_id: number; name: string }[];
    candidates: Candidate[]; // easiest to act on first
  }[];
};

export type Candidate = {
  employee_id: number;
  name: string;
  reason: "on_shift" | "busy" | "rest" | "max_hours" | "unavailable" | null; // null = free
  other_shift_id: number | null;
  other_role: string | null;
  worked_hours: number | null;
  max_hours: number | null;
};

/** One complete way to cover a call-out (not saved until chosen). */
export type RepairOption = {
  cover: { employee_id: number; name: string } | null; // null = leave the spot empty
  extra_missing: number;
  changes: number;
  fairness_change_hours: number; // negative = fairer
  cover_week_hours: number | null;
  cover_max_hours: number | null;
  cover_same_day_shift_ids: number[];
  change_list: Change[];
  assignments: Assignment[];
  shortages: Shortage[];
};

export type OptionsReport = {
  shift_id: number;
  role: string;
  options: RepairOption[]; // best first
  why: Explanation | null; // when nobody can fill the spot
};

export type Callout = {
  id: number;
  shift_id: number;
  employee_id: number;
  rest_of_day: boolean;
  note: string | null;
  reported_at: string;
};

/** A draft from the engine. `schedule` is null when no schedule was possible. */
export type DraftResult = {
  status: string;
  conflicts: string[];
  schedule: Schedule | null;
  explanation: Explanation | null; // why the call-outs can't be covered
  blockers: Blocker[]; // when nothing was found: shift roles too few people can work
};

/** A shift role that can't reach its minimum. */
export type Blocker = { shift_id: number; role: string; needed: number; available: number };

export type CalloutRisk = {
  shift_id: number;
  employee_id: number;
  employee_name: string;
  role: string;
  level: "covered" | "short" | "no_fix";
  extra_missing: number | null;
  changes: number | null;
  why: Explanation | null; // why no repair exists
};

export type RiskReport = {
  schedule_id: number;
  week_fixable: boolean;
  blocker: Explanation | null;
  baseline_missing: number;
  checked: number;
  at_risk: number;
  risks: CalloutRisk[];
};

// Staff

export type Skill = { id: number; name: string };

export type Employee = {
  id: number;
  display_name: string;
  status: "active" | "inactive";
  max_hours: number;
  target_hours: number | null;
  skills: string[];
  employee_number: string | null;
  phone: string | null;
};

export type EmployeeIn = {
  display_name: string;
  max_hours: number;
  target_hours: number | null;
  skills: string[];
  employee_number: string | null;
  phone: string | null;
};

/** Times are "HH:MM" going in; the API sends back "HH:MM:SS". */
export type WeeklyRule = { weekday: number; start_time: string; end_time: string };
export type TimeWindow = { start_time: string; end_time: string };
export type DateException = {
  date: string;
  available: boolean; // false = off all day
  intervals: TimeWindow[];
  note: string | null;
};
export type Availability = {
  employee_id: number;
  weekly: WeeklyRule[];
  exceptions: DateException[];
};

// Shifts

export type ShiftIn = {
  local_date: string;
  start_time: string; // "07:00"; an earlier end means the next day
  end_time: string;
  label: string | null;
  requirements: { role: string; count: number; min_count: number | null }[];
};

function post<T>(path: string, body: unknown = {}): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}

function send<T>(method: "PUT" | "PATCH", path: string, body: unknown): Promise<T> {
  return request<T>(path, { method, body: JSON.stringify(body) });
}

export const api = {
  restaurants: () => request<Restaurant[]>("/restaurants"),
  shifts: (restaurantId: number, week: string) =>
    request<Shift[]>(`/restaurants/${restaurantId}/weeks/${week}/shifts`),
  published: (restaurantId: number, week: string) =>
    request<Schedule>(`/restaurants/${restaurantId}/weeks/${week}/published`),

  risk: (restaurantId: number, week: string) =>
    request<RiskReport>(`/restaurants/${restaurantId}/weeks/${week}/risk`),

  callouts: (restaurantId: number, week: string) =>
    request<Callout[]>(`/restaurants/${restaurantId}/weeks/${week}/callouts`),

  cancelCallout: (restaurantId: number, calloutId: number) =>
    request<void>(`/restaurants/${restaurantId}/callouts/${calloutId}`, { method: "DELETE" }),

  callOut: (
    restaurantId: number,
    body: { shift_id: number; employee_id: number; rest_of_day: boolean; note?: string },
  ) => post<Callout>(`/restaurants/${restaurantId}/callouts`, body),

  repairOptions: (restaurantId: number, week: string, shiftId: number, employeeId: number) =>
    post<OptionsReport>(`/restaurants/${restaurantId}/weeks/${week}/repair-options`, {
      shift_id: shiftId,
      employee_id: employeeId,
    }),

  /** Save a repair as a draft; with `cover`, the chosen option from repairOptions. */
  repair: (
    restaurantId: number,
    week: string,
    cover?: { shift_id: number; role: string; employee_id: number } | null,
  ) =>
    post<DraftResult>(`/restaurants/${restaurantId}/weeks/${week}/repair`, {
      deterministic: true,
      cover: cover ?? null,
    }),

  /** A fresh draft for the week, ignoring what's published. */
  draft: (restaurantId: number, week: string) =>
    post<DraftResult>(`/restaurants/${restaurantId}/weeks/${week}/drafts`, { deterministic: true }),

  publish: (restaurantId: number, schedule: Schedule, acceptShortages: boolean) =>
    post<Schedule>(`/restaurants/${restaurantId}/schedules/${schedule.id}/publish`, {
      expected_row_version: schedule.row_version,
      accept_shortages: acceptShortages,
    }),

  // Staff
  skills: (restaurantId: number) => request<Skill[]>(`/restaurants/${restaurantId}/skills`),
  addSkill: (restaurantId: number, name: string) =>
    post<Skill>(`/restaurants/${restaurantId}/skills`, { name }),

  employees: (restaurantId: number, includeInactive = false) =>
    request<Employee[]>(
      `/restaurants/${restaurantId}/employees?include_inactive=${includeInactive}`,
    ),
  addEmployee: (restaurantId: number, body: EmployeeIn) =>
    post<Employee>(`/restaurants/${restaurantId}/employees`, body),
  updateEmployee: (
    restaurantId: number,
    employeeId: number,
    body: Partial<EmployeeIn> & { status?: Employee["status"] },
  ) => send<Employee>("PATCH", `/restaurants/${restaurantId}/employees/${employeeId}`, body),

  availability: (restaurantId: number, employeeId: number) =>
    request<Availability>(`/restaurants/${restaurantId}/employees/${employeeId}/availability`),
  setWeekly: (restaurantId: number, employeeId: number, rules: WeeklyRule[]) =>
    send<Availability>(
      "PUT",
      `/restaurants/${restaurantId}/employees/${employeeId}/availability/weekly`,
      { rules },
    ),
  setException: (
    restaurantId: number,
    employeeId: number,
    date: string,
    body: { available: boolean; intervals: TimeWindow[]; note: string | null },
  ) =>
    send<Availability>(
      "PUT",
      `/restaurants/${restaurantId}/employees/${employeeId}/availability/exceptions/${date}`,
      body,
    ),
  removeException: (restaurantId: number, employeeId: number, date: string) =>
    request<void>(
      `/restaurants/${restaurantId}/employees/${employeeId}/availability/exceptions/${date}`,
      { method: "DELETE" },
    ),

  // Shifts
  addShift: (restaurantId: number, body: ShiftIn) =>
    post<Shift>(`/restaurants/${restaurantId}/shifts`, body),
  updateShift: (restaurantId: number, shiftId: number, body: Partial<ShiftIn>) =>
    send<Shift>("PATCH", `/restaurants/${restaurantId}/shifts/${shiftId}`, body),
  deleteShift: (restaurantId: number, shiftId: number) =>
    request<void>(`/restaurants/${restaurantId}/shifts/${shiftId}`, { method: "DELETE" }),
};
