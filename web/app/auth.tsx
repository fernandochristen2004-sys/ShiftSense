"use client";

import { useState } from "react";

import { api, ApiError, type User } from "@/lib/api";

type Mode = "login" | "signup";

/** Log in, sign up, or try the demo without an account. */
export function AuthScreen({
  initialMode = "login",
  guest = false,
  onDone,
  onTryDemo,
  onCancel,
}: {
  initialMode?: Mode;
  guest?: boolean; // signing up from a guest session keeps the guest's work
  onDone: (user: User) => void;
  onTryDemo?: () => void;
  onCancel?: () => void;
}) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function switchTo(next: Mode) {
    setMode(next);
    setError(null);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    if (mode === "signup" && password !== confirm) {
      setError("The two passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      onDone(
        mode === "login" ? await api.logIn(email, password) : await api.signUp(email, password),
      );
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-10 max-w-sm rounded-lg border border-slate-200 bg-white p-6">
      <h1 className="text-2xl font-semibold">ShiftSense</h1>
      <p className="mb-5 text-sm text-slate-500">
        {guest
          ? "Sign up to keep what you made in the demo."
          : "Scheduling that recovers from call-outs"}
      </p>

      <div className="mb-5 flex rounded-md border border-slate-300 p-0.5 text-sm" role="tablist">
        {(["login", "signup"] as const).map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={mode === m}
            className={`flex-1 rounded py-1.5 ${
              mode === m ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
            }`}
            onClick={() => switchTo(m)}
            type="button"
          >
            {m === "login" ? "Log in" : "Sign up"}
          </button>
        ))}
      </div>

      <form className="space-y-3 text-sm" onSubmit={submit} noValidate>
        <label className="block">
          <span className="mb-1 block text-slate-600">Email</span>
          <input
            className={input}
            type="email"
            autoComplete="email"
            placeholder="name@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <div>
          <label className="block">
            <span className="mb-1 block text-slate-600">Password</span>
            <input
              className={input}
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              aria-describedby={mode === "signup" ? "password-hint" : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {mode === "signup" && (
            <p id="password-hint" className="mt-1 text-xs text-slate-500">
              At least 8 characters.
            </p>
          )}
        </div>
        {mode === "signup" && (
          <label className="block">
            <span className="mb-1 block text-slate-600">Confirm password</span>
            <input
              className={input}
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </label>
        )}

        {error && (
          <p className="rounded-md bg-red-50 px-3 py-2 text-red-800" role="alert">
            {error}
          </p>
        )}

        <button
          className="w-full rounded-md bg-slate-900 py-2 font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          disabled={busy}
          type="submit"
        >
          {mode === "login" ? "Log in" : "Create account"}
        </button>
      </form>

      {onTryDemo && (
        <>
          <div className="my-5 flex items-center gap-3 text-xs text-slate-400">
            <span className="grow border-t border-slate-200" />
            or
            <span className="grow border-t border-slate-200" />
          </div>
          <button
            className="w-full rounded-md border border-slate-300 py-2 text-sm hover:bg-slate-50"
            onClick={onTryDemo}
            type="button"
          >
            Try the demo, no account needed
          </button>
          <p className="mt-2 text-center text-xs text-slate-500">
            Your own private demo bistro with 25 staff
          </p>
        </>
      )}

      {onCancel && (
        <button
          className="mt-4 w-full text-center text-sm text-slate-500 hover:underline"
          onClick={onCancel}
          type="button"
        >
          Back to the demo
        </button>
      )}
    </div>
  );
}

const input = "w-full rounded-md border border-slate-300 bg-white px-2 py-1.5";
