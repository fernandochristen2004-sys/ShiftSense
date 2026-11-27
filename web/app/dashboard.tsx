"use client";

import { useEffect, useState } from "react";

import {
  api,
  ApiError,
  type Assignment,
  type Blocker,
  type Callout,
  type CalloutRisk,
  type Candidate,
  type Explanation,
  type OptionsReport,
  type RepairOption,
  type Restaurant,
  type RiskReport,
  type Schedule,
  type Shift,
  type Template,
} from "@/lib/api";
import { addDays, formatDate, formatDay, shiftCount, showTime, thisMonday } from "@/lib/dates";

import { Checklist, EmptyWeek, SaveTemplate } from "./getting-started";
import { SetupScreen } from "./setup";
import { ShiftEditor } from "./shift-editor";
import { StaffPage } from "./staff";

// The demo restaurant's week. Later this will default to the current week.
const DEMO_WEEK = "2026-11-23";

type WeekData = {
  shifts: Shift[];
  schedule: Schedule | null;
  callouts: Callout[];
  staffCount: number;
  lastWeekShifts: number;
  templates: Template[];
};

/** Someone the manager clicked, before confirming the call-out. */
type Selection = { assignment: Assignment; shift: Shift };

/** A repair waiting for the manager's approval. */
type Proposal = { calledOut: Selection; report: OptionsReport; selected: number };

/** What the grid shows while a repair is being considered. */
type Preview = { draft: Schedule };

/** A whole-week update (or a first schedule) waiting for approval. */
type Update = { draft: Schedule; first: boolean };

/** The shift form: adding one, or editing one. */
type Editing = { shift?: Shift };

/** Call-out risk per assignment, keyed by `${shift_id}-${employee_id}`. */
type RiskLookup = Map<string, CalloutRisk>;

export function Dashboard() {
  const [tab, setTab] = useState<"schedule" | "staff">("schedule");
  // A manager has one restaurant ("mine"); the demo bistro is a separate place to try things.
  const [mine, setMine] = useState<Restaurant | null>(null);
  const [demo, setDemo] = useState<Restaurant | null>(null); // set while in the demo
  const [restaurantId, setRestaurantId] = useState<number | null>(null);
  const [week, setWeek] = useState(DEMO_WEEK);
  const [data, setData] = useState<WeekData | null>(null);
  const [reloads, setReloads] = useState(0);

  const [selection, setSelection] = useState<Selection | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [update, setUpdate] = useState<Update | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [risk, setRisk] = useState<RiskReport | null>(null);
  // An explanation on screen: why a repair failed, or why a red name is red.
  const [why, setWhy] = useState<{
    explanation: Explanation;
    title: string;
    callOut?: Selection;
  } | null>(null);
  const [setup, setSetup] = useState(false); // the "Set up your restaurant" screen
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Open on your restaurant: the newest one that isn't a demo. None yet: setup.
  useEffect(() => {
    api
      .restaurants()
      .then((list) => {
        const own = list.filter((r) => !r.is_demo).at(-1) ?? null;
        setMine(own);
        if (own) {
          setRestaurantId(own.id);
          setWeek(thisMonday());
        } else {
          setSetup(true);
        }
      })
      .catch((e: ApiError) => setError(e.message));
  }, []);

  // Load the week's shifts and published schedule when the selection changes,
  // and again on coming back to the schedule (staff may have changed meanwhile).
  useEffect(() => {
    if (restaurantId === null || tab !== "schedule") return;
    let cancelled = false;

    Promise.all([
      api.shifts(restaurantId, week),
      api.published(restaurantId, week).catch((e: ApiError) => {
        if (e.code === "not_found") return null; // nothing published yet
        throw e;
      }),
      api.callouts(restaurantId, week),
      api.employees(restaurantId),
      api.shifts(restaurantId, addDays(week, -7)),
      api.templates(restaurantId),
    ])
      .then(([shifts, schedule, callouts, staff, lastWeek, templates]) => {
        if (!cancelled) {
          setData({
            shifts,
            schedule,
            callouts,
            staffCount: staff.length,
            lastWeekShifts: lastWeek.length,
            templates,
          });
        }
      })
      .catch((e: ApiError) => !cancelled && setError(e.message));

    return () => {
      cancelled = true;
    };
  }, [restaurantId, week, reloads, tab]);

  function changeView(update: () => void) {
    update();
    setSelection(null);
    setProposal(null);
    setUpdate(null);
    setEditing(null);
    setSavingTemplate(false);
    setRisk(null);
    setWhy(null);
    setError(null);
    setNotice(null);
  }

  /** Clicking a name: red names explain first, others go straight to call-out. */
  function selectPerson(next: Selection) {
    const personRisk = risk?.risks.find(
      (r) => r.shift_id === next.shift.id && r.employee_id === next.assignment.employee_id,
    );
    if (personRisk?.level === "no_fix" && personRisk.why) {
      setSelection(null);
      setWhy({
        explanation: personRisk.why,
        title: "If they call out, nobody can replace them",
        callOut: next,
      });
    } else {
      setWhy(null);
      setSelection(next);
    }
  }

  /** Simulate a call-out for every assignment and mark the risky ones. */
  async function checkRisk() {
    if (restaurantId === null) return;
    setBusy("Simulating a call-out for every shift…");
    setError(null);
    setNotice(null);
    setWhy(null);
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
    setWhy(null);
    try {
      await api.callOut(restaurantId, {
        shift_id: selection.shift.id,
        employee_id: selection.assignment.employee_id,
        rest_of_day: restOfDay,
      });
      const report = await api.repairOptions(
        restaurantId,
        week,
        selection.shift.id,
        selection.assignment.employee_id,
      );
      if (report.why) {
        setWhy({
          explanation: report.why,
          title:
            report.options.length > 0
              ? "Nobody can fill this spot. The best repair leaves it empty"
              : "No repair possible. The call-out is recorded; cancel it below if plans change",
        });
      }
      if (report.options.length > 0) {
        setProposal({ calledOut: selection, report, selected: 0 });
      } else if (!report.why) {
        setError("No repair possible. The call-out is recorded; cancel it below if plans change.");
      }
      setSelection(null);
      setReloads((n) => n + 1); // refresh the call-out list
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function cancelCallout(callout: Callout) {
    if (restaurantId === null) return;
    setBusy("Cancelling call-out…");
    setError(null);
    setNotice(null);
    try {
      await api.cancelCallout(restaurantId, callout.id);
      setProposal(null);
      setRisk(null);
      setWhy(null);
      setNotice("Call-out cancelled. Repairs and risk checks no longer include it.");
      setReloads((n) => n + 1);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function approve(acceptShortages: boolean) {
    if (!proposal || restaurantId === null) return;
    const option = proposal.report.options[proposal.selected];
    setBusy("Publishing…");
    setError(null);
    try {
      const saved = await api.repair(
        restaurantId,
        week,
        option.cover && {
          shift_id: proposal.report.shift_id,
          role: proposal.report.role,
          employee_id: option.cover.employee_id,
        },
      );
      if (!saved.schedule) {
        setError(
          "That option is no longer possible. Record the call-out again to see new options.",
        );
        setProposal(null);
        return;
      }
      const published = await api.publish(restaurantId, saved.schedule, acceptShortages);
      setProposal(null);
      setWhy(null);
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

  /**
   * Bring the published week up to date with staff, availability and shift
   * changes (and any call-outs), or make the week's first schedule.
   */
  async function proposeUpdate() {
    if (restaurantId === null || !data) return;
    const first = data.schedule === null;
    setBusy(
      first ? "Building the week's schedule…" : "Checking the week against the latest changes…",
    );
    setError(null);
    setNotice(null);
    setRisk(null);
    setWhy(null);
    setEditing(null);
    try {
      const result = first
        ? await api.draft(restaurantId, week)
        : await api.repair(restaurantId, week);
      if (!result.schedule) {
        if (result.blockers.length > 0) {
          setError(blockerMessage(result.blockers, data.shifts));
        } else if (result.explanation) {
          setWhy({
            explanation: result.explanation,
            title: "No schedule possible with the current call-outs",
          });
        } else {
          setError(
            "No schedule is possible. Every shift has enough people on paper, so it's a mix of " +
              "rules (max hours, rest between shifts): try lowering a shift's minimum or " +
              "giving staff more hours.",
          );
        }
        return;
      }
      if (!first && (result.schedule.changes ?? []).length === 0) {
        setNotice("Nothing to change: the published schedule already fits.");
        return;
      }
      setUpdate({ draft: result.schedule, first });
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function publishUpdate(acceptShortages: boolean) {
    if (!update || restaurantId === null) return;
    setBusy("Publishing…");
    setError(null);
    try {
      const published = await api.publish(restaurantId, update.draft, acceptShortages);
      setUpdate(null);
      setNotice(`Revision ${published.revision_number} is now live.`);
      setReloads((n) => n + 1);
    } catch (e) {
      const err = e as ApiError;
      setError(err.code === "stale" ? `${err.message} The page has been reloaded.` : err.message);
      if (err.code === "stale") {
        setUpdate(null);
        setReloads((n) => n + 1);
      }
    } finally {
      setBusy(null);
    }
  }

  /** Run a week-building action, then reload and say what happened. */
  async function buildWeek(label: string, action: () => Promise<string>) {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      setNotice(await action());
      setSavingTemplate(false);
      setReloads((n) => n + 1);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  const copyLastWeek = () =>
    buildWeek("Copying last week's shifts…", async () => {
      const shifts = await api.copyShifts(restaurantId!, week, addDays(week, -7));
      return `Copied ${shiftCount(shifts.length)} from last week. Click Create schedule to staff them.`;
    });

  const useTemplate = (template: Template) =>
    buildWeek(`Adding "${template.name}"…`, async () => {
      const shifts = await api.applyTemplate(restaurantId!, week, template.id);
      return `Added ${shiftCount(shifts.length)} from "${template.name}". Click Create schedule to staff them.`;
    });

  const deleteTemplate = (template: Template) =>
    buildWeek("Deleting template…", async () => {
      await api.deleteTemplate(restaurantId!, template.id);
      return `Deleted the template "${template.name}". Weeks made from it keep their shifts.`;
    });

  const saveTemplate = (name: string) =>
    buildWeek("Saving template…", async () => {
      const template = await api.saveTemplate(restaurantId!, name, week);
      return `Saved "${template.name}" (${shiftCount(template.shift_count)}). Use it on any empty week.`;
    });

  function created(restaurant: Restaurant, isDemo: boolean) {
    if (isDemo) {
      enterDemo(restaurant);
      return;
    }
    setMine(restaurant);
    changeView(() => {
      setDemo(null);
      setRestaurantId(restaurant.id);
      setWeek(thisMonday());
      setTab("schedule");
      setSetup(false);
    });
  }

  function enterDemo(restaurant: Restaurant) {
    changeView(() => {
      setDemo(restaurant);
      setRestaurantId(restaurant.id);
      setWeek(DEMO_WEEK);
      setTab("schedule");
      setSetup(false);
    });
  }

  async function openDemo(reset: boolean) {
    setBusy(reset ? "Making a fresh demo…" : "Opening the demo…");
    setError(null);
    try {
      enterDemo(await api.openDemo(reset));
      if (reset) setNotice("Fresh demo ready: everything is back to the start.");
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  /** Leave the demo: back to your restaurant, or to setup if you haven't made one. */
  function leaveDemo() {
    changeView(() => {
      setDemo(null);
      setTab("schedule");
      if (mine) {
        setRestaurantId(mine.id);
        setWeek(thisMonday());
      } else {
        setRestaurantId(null);
        setSetup(true);
      }
    });
  }

  const restaurant = demo ?? mine;
  const reviewing = proposal !== null || update !== null;

  return (
    <main className="mx-auto max-w-7xl p-6">
      {demo && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
          <span className="grow">
            You&apos;re in the demo: a made-up bistro to try things out.
            {mine && ` Nothing here touches ${mine.name}.`}
          </span>
          <button
            className="rounded-md border border-amber-400 bg-white px-3 py-1 hover:bg-amber-100"
            onClick={leaveDemo}
          >
            ← {mine ? `Back to ${mine.name}` : "Back to setup"}
          </button>
          <button
            className="rounded-md border border-amber-400 bg-white px-3 py-1 hover:bg-amber-100"
            onClick={() => openDemo(true)}
            title="Start the demo again from scratch"
          >
            Reset demo
          </button>
        </div>
      )}

      <header className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">ShiftSense</h1>
          <p className="text-sm text-slate-500">
            {setup
              ? "New restaurant"
              : restaurant
                ? `${restaurant.name} · ${restaurant.timezone}`
                : "Loading…"}
          </p>
        </div>

        <nav
          className={`flex rounded-md border border-slate-300 bg-white p-0.5 text-sm ${
            setup ? "invisible" : ""
          }`}
        >
          {(["schedule", "staff"] as const).map((name) => (
            <button
              key={name}
              className={`rounded px-3 py-1 capitalize ${
                tab === name ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
              }`}
              onClick={() => changeView(() => setTab(name))}
            >
              {name}
            </button>
          ))}
        </nav>

        <div className="flex items-center gap-3">
          {!setup && !demo && mine && (
            <button
              className="text-sm text-sky-800 hover:underline"
              onClick={() => openDemo(false)}
              title="A made-up bistro with 25 staff, to try call-outs and repairs safely"
            >
              Try the demo
            </button>
          )}

          {tab === "schedule" && !setup && (
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
          )}
        </div>
      </header>

      {setup && <SetupScreen onCreated={created} />}

      {!setup && tab === "staff" && restaurantId !== null && (
        <StaffPage restaurantId={restaurantId} />
      )}

      {!setup && tab === "schedule" && (
        <>
          {error && <Banner tone="red">{error}</Banner>}
          {notice && <Banner tone="green">{notice}</Banner>}
          {busy && <Banner tone="slate">{busy}</Banner>}

          {risk && !reviewing && !busy && data && (
            <RiskSummary report={risk} shifts={data.shifts} onClose={() => setRisk(null)} />
          )}

          {why && data && !busy && (
            <WhyPanel
              title={why.title}
              explanation={why.explanation}
              shifts={data.shifts}
              onCallOut={
                why.callOut
                  ? () => {
                      setSelection(why.callOut!);
                      setWhy(null);
                    }
                  : undefined
              }
              onClose={() => setWhy(null)}
            />
          )}

          {data && data.callouts.length > 0 && !reviewing && (
            <CalloutList
              callouts={data.callouts}
              shifts={data.shifts}
              published={data.schedule}
              onCancel={busy ? undefined : cancelCallout}
            />
          )}

          {selection && !busy && (
            <CalloutPanel
              selection={selection}
              onConfirm={callOut}
              onCancel={() => setSelection(null)}
            />
          )}

          {proposal && !busy && data?.schedule && (
            <OptionsPanel
              proposal={proposal}
              published={data.schedule}
              shifts={data.shifts}
              callouts={data.callouts}
              onSelect={(index) => setProposal({ ...proposal, selected: index })}
              onApprove={approve}
              onDiscard={() => {
                setProposal(null);
                setWhy(null);
              }}
            />
          )}

          {data && restaurant && data.lastWeekShifts === 0 && !reviewing && (
            <Checklist
              name={restaurant.name}
              staffCount={data.staffCount}
              shiftCount={data.shifts.length}
              published={data.schedule !== null}
              onAddStaff={() => changeView(() => setTab("staff"))}
            />
          )}

          {data && data.shifts.length > 0 && !reviewing && !busy && restaurantId !== null && (
            <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
              <button
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 hover:bg-slate-100"
                onClick={() => {
                  setWhy(null);
                  setNotice(null);
                  setError(null);
                  setEditing({});
                }}
              >
                + Add shift
              </button>
              {data.shifts.length > 0 && (
                <button
                  className="rounded-md bg-slate-900 px-3 py-1.5 font-medium text-white hover:bg-slate-700"
                  onClick={proposeUpdate}
                  title="Re-plan the week after staff, hours or shift changes, changing as little as possible"
                >
                  {data.schedule ? "Update schedule" : "Create schedule"}
                </button>
              )}
              <span className="ml-auto">
                {savingTemplate ? (
                  <SaveTemplate onSave={saveTemplate} onCancel={() => setSavingTemplate(false)} />
                ) : (
                  <button
                    className="text-slate-600 hover:underline"
                    onClick={() => setSavingTemplate(true)}
                    title="Reuse this week's shifts and needs on another week"
                  >
                    Save week as template
                  </button>
                )}
              </span>
            </div>
          )}

          {editing && restaurantId !== null && !busy && (
            <ShiftEditor
              key={editing.shift?.id ?? "new"}
              restaurantId={restaurantId}
              week={week}
              shift={editing.shift}
              onSaved={(message) => {
                setEditing(null);
                setNotice(message);
                setReloads((n) => n + 1);
              }}
              onClose={() => setEditing(null)}
            />
          )}

          {update && data && !busy && (
            <UpdatePanel
              update={update}
              published={data.schedule}
              shifts={data.shifts}
              onApprove={publishUpdate}
              onDiscard={() => setUpdate(null)}
            />
          )}

          {data && data.shifts.length === 0 && !editing && !busy && (
            <EmptyWeek
              lastWeekShifts={data.lastWeekShifts}
              templates={data.templates}
              onAdd={() => {
                setNotice(null);
                setError(null);
                setEditing({});
              }}
              onCopyLastWeek={copyLastWeek}
              onUseTemplate={useTemplate}
              onDeleteTemplate={deleteTemplate}
            />
          )}

          {data && data.shifts.length > 0 && (
            <WeekView
              week={week}
              shifts={data.shifts}
              published={data.schedule}
              proposal={
                update
                  ? { draft: update.draft }
                  : proposal && data.schedule
                    ? previewOf(proposal, data.schedule)
                    : null
              }
              selection={selection}
              risks={risk && !reviewing ? riskLookup(risk) : null}
              onCheckRisk={busy || reviewing ? undefined : checkRisk}
              onSelect={busy || reviewing ? undefined : selectPerson}
              onEditShift={
                busy || reviewing
                  ? undefined
                  : (shift) => {
                      setWhy(null);
                      setNotice(null);
                      setError(null);
                      setEditing({ shift });
                    }
              }
            />
          )}
        </>
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

/** A re-planned week (or a first schedule), waiting for the manager's approval. */
function UpdatePanel({
  update,
  published,
  shifts,
  onApprove,
  onDiscard,
}: {
  update: Update;
  published: Schedule | null;
  shifts: Shift[];
  onApprove: (acceptShortages: boolean) => void;
  onDiscard: () => void;
}) {
  const [acceptShortages, setAcceptShortages] = useState(false);
  const { draft, first } = update;
  const missing = totalMissing(draft);
  const names = nameLookup(draft, ...(published ? [published] : []));
  const changes = draft.changes ?? [];
  const byShift = new Map(shifts.map((s) => [s.id, s]));

  return (
    <div className="mb-4 rounded-lg border border-sky-300 bg-sky-50 p-4 text-sm">
      <h2 className="mb-1 font-semibold">
        {first
          ? `New schedule: ${draft.assignments.length} assignments`
          : `${changes.length} change${changes.length === 1 ? "" : "s"} to bring the week up to date`}
      </h2>
      <p className="mb-3 text-slate-600">
        {first
          ? "Shown in the grid below. Nothing is live until you publish."
          : "Picked to change as little as possible. Shown in the grid below."}
        {missing > 0 && ` Still ${missing} position(s) short.`}
      </p>

      {!first && (
        <ul className="mb-3 max-h-48 space-y-0.5 overflow-y-auto">
          {changes.map((c) => {
            const shift = byShift.get(c.shift_id);
            const where = shift ? shiftName(shift) : "a removed shift";
            const name = names.get(c.employee_id) ?? `#${c.employee_id}`;
            return (
              <li
                key={`${c.shift_id}-${c.employee_id}`}
                className={c.after_role ? "text-emerald-800" : "text-red-700"}
              >
                {c.after_role
                  ? `+ ${name} on ${where} (${c.after_role}${c.before_role ? `, was ${c.before_role}` : ""})`
                  : `− ${name} off ${where} (${c.before_role})`}
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {missing > 0 && (
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={acceptShortages}
              onChange={(e) => setAcceptShortages(e.target.checked)}
            />
            Publish with {missing} position(s) short
          </label>
        )}
        <button
          className="rounded-md bg-emerald-700 px-3 py-1.5 font-medium text-white hover:bg-emerald-800 disabled:opacity-40"
          disabled={missing > 0 && !acceptShortages}
          onClick={() => onApprove(acceptShortages)}
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

/** The grid's view of an option: the published week with the option applied. */
function previewOf(proposal: Proposal, published: Schedule): Preview {
  const option = proposal.report.options[proposal.selected];
  return {
    draft: {
      ...published,
      status: "draft",
      revision_number: published.revision_number + 1,
      assignments: option.assignments,
      changes: option.change_list,
      shortages: option.shortages,
    },
  };
}

function OptionsPanel({
  proposal,
  published,
  shifts,
  callouts,
  onSelect,
  onApprove,
  onDiscard,
}: {
  proposal: Proposal;
  published: Schedule;
  shifts: Shift[];
  callouts: Callout[];
  onSelect: (index: number) => void;
  onApprove: (acceptShortages: boolean) => void;
  onDiscard: () => void;
}) {
  const { report, calledOut, selected } = proposal;
  const option = report.options[selected];
  const missing = option.shortages.reduce((total, s) => total + s.missing, 0);
  const [accepted, setAccepted] = useState(false);
  const names = nameLookup(published, previewOf(proposal, published).draft);
  const where = shiftName(calledOut.shift);
  const count = report.options.length;

  return (
    <div className="mb-4 rounded-lg border border-sky-300 bg-sky-50 px-4 py-3 text-sm">
      <p className="mb-3">
        <strong>
          {count === 1 ? "1 way" : `${count} ways`} to cover {calledOut.assignment.employee_name}
          &apos;s {where} ({report.role})
        </strong>
        <span className="text-slate-500"> · best first; pick one to preview it below</span>
      </p>

      <div className="mb-3 grid gap-3 md:grid-cols-3">
        {report.options.map((choice, index) => (
          <button
            key={choice.cover?.employee_id ?? "empty"}
            onClick={() => {
              onSelect(index);
              setAccepted(false);
            }}
            className={`rounded-lg border bg-white px-4 py-3 text-left ${
              index === selected
                ? "border-sky-500 ring-2 ring-sky-200"
                : "border-slate-200 hover:border-slate-400"
            }`}
          >
            <p className="mb-1 flex items-center gap-2 font-medium">
              {choice.cover ? `${choice.cover.name} covers it` : "Leave the spot empty"}
              {index === 0 && <Badge tone="green">Best</Badge>}
              {index > 0 && sameRank(choice, report.options[0]) && (
                <Badge tone="green">Equally good</Badge>
              )}
            </p>
            <ul className="space-y-0.5 text-slate-600">
              {optionFacts(choice, report.options[0], calledOut, callouts, names, shifts).map(
                (fact) => (
                  <li key={fact}>{fact}</li>
                ),
              )}
            </ul>
          </button>
        ))}
      </div>

      <p className="mb-1 text-xs text-slate-500">What changes with this option</p>
      <ul className="mb-3 space-y-0.5">
        {option.change_list.map((change) => {
          const shift = shifts.find((s) => s.id === change.shift_id);
          const name = names.get(change.employee_id) ?? `#${change.employee_id}`;
          const at = shift ? shiftName(shift) : `shift ${change.shift_id}`;
          return (
            <li key={`${change.shift_id}-${change.employee_id}`}>
              {change.after_role === null ? (
                <span className="text-red-700">
                  − {name} off {at} ({change.before_role})
                </span>
              ) : change.before_role === null ? (
                <span className="text-emerald-700">
                  + {name} on {at} ({change.after_role})
                </span>
              ) : (
                <span className="text-sky-800">
                  ~ {name} on {at}: {change.before_role} → {change.after_role}
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

/** Same ranking as the best option: as short, as few changes, as fair, same load. */
function sameRank(option: RepairOption, best: RepairOption): boolean {
  const load = (o: RepairOption) =>
    o.cover_week_hours !== null && o.cover_max_hours ? o.cover_week_hours / o.cover_max_hours : 0;
  return (
    option.extra_missing === best.extra_missing &&
    option.changes === best.changes &&
    option.fairness_change_hours === best.fairness_change_hours &&
    load(option) === load(best)
  );
}

/** Short reasons to pick (or not pick) an option, compared with the best one. */
function optionFacts(
  option: RepairOption,
  best: RepairOption,
  calledOut: Selection,
  callouts: Callout[],
  names: Map<number, string>,
  shifts: Shift[],
): string[] {
  const facts = [`${option.changes} change${option.changes === 1 ? "" : "s"} to the week`];
  const calledOutId = calledOut.assignment.employee_id;
  const moved = new Set(option.change_list.map((c) => c.employee_id));

  // Earlier call-outs this repair also deals with.
  const earlier = callouts
    .map((c) => c.employee_id)
    .filter((id, i, all) => id !== calledOutId && moved.has(id) && all.indexOf(id) === i);
  if (earlier.length > 0) {
    const who = earlier.map((id) => names.get(id) ?? `#${id}`).join(", ");
    facts.push(`Also covers earlier call-outs: ${who}`);
  }

  // Anyone else moved besides the people who called out and this cover.
  const others = new Set(
    [...moved].filter(
      (id) => id !== calledOutId && id !== option.cover?.employee_id && !earlier.includes(id),
    ),
  );
  if (others.size > 0) {
    facts.push(
      `Also moves ${others.size} other ${others.size === 1 ? "person" : "people"} ` +
        "to fill other gaps or stay within the rules",
    );
  }
  if (option.extra_missing > 0) {
    facts.push(`Leaves ${option.extra_missing} more position(s) short`);
  }
  if (option.cover && option.cover_week_hours !== null) {
    facts.push(
      `${option.cover.name}: ${round(option.cover_week_hours)} of ${option.cover_max_hours} h this week`,
    );
  }
  for (const id of option.cover_same_day_shift_ids) {
    const shift = shifts.find((s) => s.id === id);
    if (shift) facts.push(`Also works ${shiftName(shift)}`);
  }
  // Fairness only matters in comparison: the called-out person's lost hours
  // affect every option the same way.
  const fairness = option.fairness_change_hours - best.fairness_change_hours;
  if (fairness > 0) facts.push(`Hours less even than the best option (+${round(fairness)} h)`);
  else if (fairness < 0) facts.push(`Hours more even than the best option (${round(-fairness)} h)`);
  return facts;
}

function round(hours: number): string {
  return Number.isInteger(hours) ? String(hours) : hours.toFixed(1);
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
  onEditShift,
}: {
  week: string;
  shifts: Shift[];
  published: Schedule | null;
  proposal: Preview | null;
  selection: Selection | null;
  risks: RiskLookup | null;
  onCheckRisk?: () => void;
  onSelect?: (selection: Selection) => void;
  onEditShift?: (shift: Shift) => void;
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
              {proposal ? "Showing the proposed changes" : "Click a name to record a call-out"}
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
          <>
            <Badge tone="slate">Nothing published for this week yet</Badge>
            {proposal && <span className="text-slate-500">Showing the proposed schedule</span>}
          </>
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
                    <span className="whitespace-nowrap">{showTime(slot.start)}</span>–
                    <span className="whitespace-nowrap">{showTime(slot.end)}</span>
                  </div>
                </td>
                {days.map((day) => {
                  const shift = shifts.find((s) => s.local_date === day && slotKey(s) === slot.key);
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
                          onEdit={onEditShift}
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
  onEdit,
}: {
  shift: Shift;
  schedule: Schedule | null;
  proposal: Preview | null;
  names: Map<number, string> | null;
  selection: Selection | null;
  risks: RiskLookup | null;
  onSelect?: (selection: Selection) => void;
  onEdit?: (shift: Shift) => void;
}) {
  const changes = proposal?.draft.changes ?? [];

  return (
    <div className="group space-y-2">
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
      {onEdit && (
        <button
          className="text-[11px] text-slate-400 opacity-0 hover:text-sky-700 hover:underline focus:opacity-100 group-hover:opacity-100"
          onClick={() => onEdit(shift)}
        >
          Edit shift
        </button>
      )}
    </div>
  );
}

function RiskSummary({
  report,
  shifts,
  onClose,
}: {
  report: RiskReport;
  shifts: Shift[];
  onClose: () => void;
}) {
  const count = (level: CalloutRisk["level"]) =>
    report.risks.filter((r) => r.level === level).length;

  if (!report.week_fixable && report.blocker) {
    return (
      <WhyPanel
        title="A call-out already recorded this week can't be covered, so nothing else can be checked"
        explanation={report.blocker}
        shifts={shifts}
        onClose={onClose}
      />
    );
  }

  if (!report.week_fixable) {
    return (
      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
        <strong>Call-out risk</strong>
        <span>
          A call-out already recorded this week can&apos;t be covered, so no repair is possible
          right now.
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
      <span className="text-slate-500">Hover a name for details; click a red one to see why.</span>
      <button className="ml-auto text-slate-600 hover:underline" onClick={onClose}>
        Hide
      </button>
    </div>
  );
}

/** Why a gap can't be filled, laid out as a card per gap. */
function WhyPanel({
  title,
  explanation,
  shifts,
  onCallOut,
  onClose,
}: {
  title: string;
  explanation: Explanation;
  shifts: Shift[];
  onCallOut?: () => void;
  onClose: () => void;
}) {
  return (
    <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm">
      <p className="mb-3 font-medium text-red-800">{title}</p>
      <div className="flex flex-wrap gap-3">
        {explanation.gaps.map((gap) => {
          const shift = shifts.find((s) => s.id === gap.shift_id);
          const who = gap.called_out.map((p) => p.name).join(", ");
          return (
            <div
              key={`${gap.shift_id}-${gap.role}`}
              className="min-w-72 flex-1 rounded-lg border border-slate-200 bg-white px-4 py-3"
            >
              <p className="flex items-center gap-2 font-medium">
                <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-600" />
                {who} can&apos;t be replaced
              </p>
              <p className="mb-2 ml-[18px] text-slate-500">
                {shift ? shiftName(shift) : `shift ${gap.shift_id}`} · {gap.role}
              </p>
              <div className="border-t border-slate-100 pt-2">
                {gap.candidates.length === 0 ? (
                  <p className="text-slate-600">Nobody else works {gap.role}.</p>
                ) : (
                  <>
                    <p className="mb-1 text-xs text-slate-500">Other {gap.role}s</p>
                    <table className="w-full">
                      <tbody>
                        {groupByReason(gap.candidates, shifts).map(([label, names]) => (
                          <tr key={label} className="align-top">
                            <td className="w-44 py-0.5 pr-3 text-slate-500">{label}</td>
                            <td className="py-0.5">{names.join(", ")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {explanation.together_only && (
        <p className="mt-2 text-slate-600">
          Each gap has someone free on their own, but not all at once.
        </p>
      )}
      <div className="mt-3 flex gap-3">
        {onCallOut && (
          <button
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 hover:bg-slate-100"
            onClick={onCallOut}
          >
            Call out anyway
          </button>
        )}
        <button className="px-2 py-1.5 text-slate-600 hover:underline" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}

/** Candidates grouped by a short reason, keeping the API's order. */
function groupByReason(candidates: Candidate[], shifts: Shift[]): [string, string[]][] {
  const groups = new Map<string, string[]>();
  for (const candidate of candidates) {
    const label = reasonLabel(candidate, shifts);
    groups.set(label, [...(groups.get(label) ?? []), candidate.name]);
  }
  return [...groups.entries()];
}

function reasonLabel(candidate: Candidate, shifts: Shift[]): string {
  const other = shifts.find((s) => s.id === candidate.other_shift_id);
  const otherName = other ? shiftName(other) : "another shift";
  switch (candidate.reason) {
    case "on_shift":
      return `On this shift as ${candidate.other_role}`;
    case "busy":
      return `Working ${otherName}`;
    case "rest":
      return `Needs rest (works ${otherName})`;
    case "max_hours":
      return "At max hours";
    case "unavailable":
      return "Not available";
    default:
      return "Free on their own";
  }
}

function CalloutList({
  callouts,
  shifts,
  published,
  onCancel,
}: {
  callouts: Callout[];
  shifts: Shift[];
  published: Schedule | null;
  onCancel?: (callout: Callout) => void;
}) {
  const names = published ? nameLookup(published) : new Map<number, string>();

  return (
    <div className="mb-4 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm">
      <strong className="mr-3">Call-outs this week</strong>
      <ul className="mt-1 space-y-1">
        {callouts.map((callout) => {
          const shift = shifts.find((s) => s.id === callout.shift_id);
          return (
            <li key={callout.id} className="flex items-center gap-3">
              <span>
                {names.get(callout.employee_id) ?? `#${callout.employee_id}`} ·{" "}
                {shift ? shiftName(shift) : `shift ${callout.shift_id}`}
                {callout.rest_of_day && <span className="text-slate-500"> (rest of day)</span>}
                {callout.note && <span className="text-slate-500"> · {callout.note}</span>}
              </span>
              {onCancel && (
                <button
                  className="text-slate-600 hover:text-red-700 hover:underline"
                  onClick={() => onCancel(callout)}
                >
                  Cancel
                </button>
              )}
            </li>
          );
        })}
      </ul>
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
    return `If ${name} calls out, nobody can replace them. Click for why.`;
  }
  if (risk.level === "short") {
    return `If ${name} calls out: leaves ${risk.extra_missing} position(s) short`;
  }
  return `If ${name} calls out: covered with ${risk.changes} change(s)`;
}

// Small pieces

function Banner({
  tone,
  children,
}: {
  tone: "red" | "green" | "slate";
  children: React.ReactNode;
}) {
  const colours = {
    red: "border-red-200 bg-red-50 text-red-800",
    green: "border-emerald-200 bg-emerald-50 text-emerald-800",
    slate: "border-slate-200 bg-white text-slate-700",
  };
  return <p className={`mb-4 rounded-md border px-4 py-3 text-sm ${colours[tone]}`}>{children}</p>;
}

function Badge({
  tone,
  children,
}: {
  tone: "green" | "amber" | "slate";
  children: React.ReactNode;
}) {
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

/** "No schedule is possible: Tue 24 breakfast (07:00–11:00) needs 1 server, but nobody … */
function blockerMessage(blockers: Blocker[], shifts: Shift[]): string {
  const byId = new Map(shifts.map((s) => [s.id, s]));
  const parts = blockers.slice(0, 3).map((b) => {
    const shift = byId.get(b.shift_id);
    const where = shift
      ? `${shiftName(shift)} (${showTime(shift.local_start)}–${showTime(shift.local_end)})`
      : "A shift";
    const free =
      b.available === 0
        ? `nobody with that role is free then`
        : `only ${b.available} ${b.available === 1 ? "is" : "are"} free then`;
    return `${where} needs ${b.needed} ${b.role}${b.needed === 1 ? "" : "s"}, but ${free}`;
  });
  const more = blockers.length > 3 ? ` (and ${blockers.length - 3} more)` : "";
  return (
    `No schedule is possible. ${parts.join("; ")}${more}. ` +
    "Give someone with that role hours that cover the shift (Staff tab), or lower the shift's minimum."
  );
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
  if (hour < 11) return "Breakfast";
  if (hour < 15) return "Lunch";
  if (hour < 22) return "Dinner";
  return "Late close";
}
