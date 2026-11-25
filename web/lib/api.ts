// Talks to the ShiftSense API. Types mirror api/stored_schemas.py.

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
  return response.json() as Promise<T>;
}

export const api = {
  restaurants: () => request<Restaurant[]>("/restaurants"),
  shifts: (restaurantId: number, week: string) =>
    request<Shift[]>(`/restaurants/${restaurantId}/weeks/${week}/shifts`),
  published: (restaurantId: number, week: string) =>
    request<Schedule>(`/restaurants/${restaurantId}/weeks/${week}/published`),
};
