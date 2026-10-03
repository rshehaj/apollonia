---
name: milestone
description: Run one Apollonia milestone end to end (spec, plan, test-first implementation with independent review, verification and handoff), resuming wherever it stopped. Use when the maintainer says "/milestone M<n>" or asks to continue a milestone.
argument-hint: M<n>
---

# /milestone — autonomous milestone cycle

You are the **orchestrator**. You coordinate; the `implementer` and `reviewer` agents do the
per-task work. `CLAUDE.md` ground rules apply throughout. Above all: no `git`, and no paid API
calls without approval.

## 0. Locate state

Resolve the milestone id from the arguments (e.g. `M2`). Then find:
- **Spec:** the milestone's section in `docs/specs/*-design.md`, or a dedicated spec for it.
- **Plan:** the plan file for this milestone (location given in local instructions, if any).
  Unchecked `- [ ]` steps are the remaining work.

Go to the first stage that is not complete.

## 1. Spec (human gate)

If the milestone has no detailed spec: brainstorm with the maintainer (one question at a time),
write the spec, self-review it, and **stop for approval**.

## 2. Plan (human gate)

If there is no plan: write a test-first, task-by-task plan with exact code and commands,
Interfaces blocks, Global Constraints and Review Focus. **Stop for approval.**

After approval, sync GitHub (see "Issue tracking" in `CLAUDE.md`): create the milestone's task
issues with the standard body sections and labels, assign them to the GitHub milestone, and add
the task list to the milestone's epic. Record the task → issue mapping in the plan.

## 3. Build loop (autonomous)

For each task with unchecked steps, in order:

1. **Implement:** dispatch the `implementer` agent with the plan path, task number and spec path.
2. **Gate:** if it reports DONE, run `scripts/check.sh` yourself and confirm it is green.
3. **Review:** dispatch the `reviewer` agent with the task number and the implementer's report.
4. **Fix loop:** on CHANGES_REQUESTED, send the findings back to a new `implementer` run, then
   re-review. **Max 2 fix rounds**, then escalate.
5. **Record:** tick the task's checkboxes in the plan, and follow any local per-task instructions
   (e.g. notes). Keep a running list of files per task for the handoff.
6. Post **one** completion comment on the task's issue: what was built, test count, review
   verdict and the fixes it led to. Deferred review findings become new `review-follow-up` issues
   linked from the epic.
7. Post one short progress line to the maintainer (`Task N ✓: <name> (#issue)`), then continue.

## 4. Verify

Run the plan's verification task(s) end to end (real data, CLI, evaluations). Any step that
calls a paid API: **stop and ask**, with an estimated cost.

## 5. Final review

Dispatch the `reviewer` agent for the **whole milestone**. Fix blockers and majors (same loop
and limits as above).

## 6. Handoff (human gate)

Report to the maintainer:
- What was built (3–6 bullets), with key numbers (tests, eval metrics).
- Deviations from the plan, and open follow-ups.
- **Ready-to-paste git commands:** one `git add …` + `git commit -m "<conventional message>"`
  per task, in order, each ending with `Closes #<issue>`, then the release tag if the plan
  defines one.

## Escalate immediately (stop and ask) when

- an implementer reports BLOCKED, or 2 fix rounds did not reach APPROVED;
- the spec or plan is ambiguous, or a change would alter a cross-task interface;
- a new dependency, paid API call, destructive action or personal information is needed.

When escalating, state the task, what was tried, the options, and your recommendation. Also
label the task's issue `status: needs-decision` and comment there with the question.
