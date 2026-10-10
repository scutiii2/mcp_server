# Usage ownership implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement task by task after this plan is approved. Steps use checkbox syntax.

**Goal:** Keep Ember Web usage personal and provide per-user usage inspection in Ember Admin.
**Architecture:** Reuse the existing UsageService through distinct personal and admin routes. Keep presentation helpers local to each client, following the existing LineChart copy convention.
**Tech Stack:** FastAPI, async SQLAlchemy, Vue 3, TypeScript, Pinia, Vitest and Playwright.
**Spec:** [Usage ownership design](../specs/2026-10-10-usage-ownership-design.md)

## Global constraints

- Planning targets main at d414983; preserve unrelated working-tree changes.
- Personal usage requires chat.use; admin usage requires usage.all.view.
- No new permission, dependency, schema migration, upstream call or shared frontend package.
- Retain UTC periods, local display times and current response shapes.
- Colors and radii use existing style.css tokens. Never expose other users' chat contents.
- Implementation, commits, push and deployment require their own authorization; this request is planning only.

## Review focus

- An account with only usage.all.view can inspect usage without chat.use or accounts.view.
- Zero-usage and disabled users remain discoverable; deleted selection returns to the summary.
- Delegated rows count as one answer per chat turn; summaries contribute tokens but not answers.
- Late user/period responses and account changes never display or export another selection's data.
- Optional-section failures preserve the report; main errors never masquerade as zero usage.

## Task 1: Admin usage API and accurate account summaries

**Files:** Modify apps/Ember/ember_api/src/routes/usage.py,
apps/Ember/ember_api/src/services/usage_service.py and apps/Ember/ember_api/README.md.
Create apps/Ember/ember_api/tests/test_admin_usage.py; extend tests/test_usage_report.py.

**Interfaces:** Reuse UsageService.windows(account_id), report(account_id, days,
since_date, *, group_by, agent, provider), records(account_id, days, since_date, *,
agent, provider, limit), UsageOut and UsageRecordOut. Produce the two admin detail
routes and the corrected existing summary endpoint exactly as specified.

- [ ] Add failing API tests with two accounts whose token totals and records differ.
  Assert personal reads return only the caller; admin target reads return only the
  target, including rolling limits, grouping, filters and period boundaries.
- [ ] Cover 401 logged out, 403 without usage.all.view or when verification is
  required, success for a verified usage-only role, 404 missing target, 422 invalid
  IDs/days/since/grouping/limit, and valid zero-usage detail.
- [ ] Add summary tests: zero/disabled accounts included; out-of-period usage yields
  zero and null last-used; multiple delegated rows for one chat count one answer;
  summary-only usage has tokens but zero answers; stable ordering for tied totals.
- [ ] Run the new tests to confirm failures are caused by missing behavior.
- [ ] Implement admin routes using require_admin, target lookup and existing service
  methods/serializers. Change all_accounts aggregation to the period-filtered outer
  join and distinct non-summary answer count; add deterministic tie ordering.
- [ ] Run .venv_ember_api/Scripts/python -m pytest -q from apps/Ember/ember_api.
  Expect all tests to pass. Update the README API table and counting semantics.

## Task 2: Personal-only Ember Web Usage

**Files:** Modify apps/Ember/ember_web/src/views/UsageView.vue and UsageView.test.ts;
src/api/UsageClient.ts and UsageClient.test.ts; src/router/index.ts, index.test.ts
and pages.ts; README.md; affected navigation tests and e2e/fakeApi.ts if necessary.

**Interfaces:** Keep usageClient.mine and records unchanged. Remove allAccounts and
AccountUsage from Web. /usage and its navigation entry require chat.use.

- [ ] Replace all-accounts expectations with a regression test asserting an admin
  with chat.use sees only personal usage and issues no /api/admin/usage request.
  Retain existing personal report, period, chart, breakdown, recent-call and export tests.
- [ ] Add router/navigation tests: chat.use opens Usage; usage.all.view alone cannot
  open or land on it; unauthenticated direct links preserve the login redirect.
- [ ] Run focused tests and confirm the new assertions fail before changing behavior.
- [ ] Remove admin-only usage state, fetch, rendering and client types/method.
  Tighten route and NAV_PAGES rules and remove the usage.all.view HOME_PAGES fallback.
  Keep all personal features and associated styles intact.
- [ ] Run npm test, npx vue-tsc -b, npm run build and npm run test:e2e from
  apps/Ember/ember_web. Expect all to pass; update README ownership description.

## Task 3: Admin Usage summary and detailed reports

**Files:** Create apps/Ember/ember_admin/src/api/UsageClient.ts and UsageClient.test.ts;
src/views/UsageView.vue and UsageView.test.ts; src/components/usage/UsageDetails.vue
and UsageDetails.test.ts; local helpers src/utils/usageFormat.ts, usageStats.ts,
usageHeatmap.ts, usageExport.ts and focused tests; src/components/UsageHeatmap.vue
and test; src/utils/downloadText.ts and test.
Modify src/router/index.ts, index.test.ts and pages.ts;
src/views/AdminOverviewView.vue; README.md. Extend existing nav/overview tests.

**Interfaces:** Admin usageClient exports allAccounts(days, since?), account(accountId,
days, since?, options?) -> Promise<MyUsage>, and records(accountId, days, since?,
options?) -> Promise<UsageRecordRow[]> through apiRequest. Reuse existing Web response
interfaces and query semantics locally, mapping account() to the admin detail route.
UsageDetails accepts the selected username, loaded report/records/annual data and
loading/error state; emits grouping changes and export requests. It performs no
personal endpoint calls. Reuse admin LineChart and shared controls.

- [ ] Write client tests for all three URLs, encoded filters, correct target IDs,
  response typing and error propagation. Confirm failures, then implement the client.
- [ ] Add failing route/nav tests for usage.all.view visibility and access; a
  usage-only login can discover Usage through the overview, while missing permission
  and unverified accounts follow existing guards.
- [ ] Add view tests for summary selection, correct user/period/grouping requests,
  zero usage, independent 366-day heatmap, target labels and loaded-user export.
  Assert no personal /api/usage calls and no dependency on account-list permission.
- [ ] Add deferred-promise tests for A->B selection races and rapid period changes;
  old replies must not update report, records or heatmap. Cover logged-in account
  changes, export disabled while changing selection, deleted users, summary/detail
  retry, and optional-section failure without loss of the report.
- [ ] Implement /usage, ADMIN_PAGES and ADMIN_PERMISSIONS changes plus overview
  description. Implement summary and selection state in UsageView and presentation
  in UsageDetails. Reuse tested Web helpers locally where needed; use existing admin
  utilities where available rather than duplicating them. Copy the heatmap with
  token-based styles. Keep export labels tied to successfully loaded data.
- [ ] Run npm test, npx vue-tsc -b and npm run build from apps/Ember/ember_admin.
  Expect all to pass, including radiusScale.test.ts. Update README features.

## Task 4: Browser proof of the ownership split

**Files:** Create apps/Ember/ember_admin/e2e/usage.spec.ts and
apps/Ember/ember_web/e2e/usage.spec.ts. Modify their existing e2e/fakeApi.ts fixtures.

**Interfaces:** Fake APIs implement the documented personal/admin usage responses;
at least two users have distinct totals, plus a zero-usage account.

- [ ] Add browser checks proving Web stays personal for an administrator and Admin
  lists users and switches all detail panels and export identity to the selected user.
- [ ] Cover a usage-only admin role and denial without usage.all.view. Exercise
  period and grouping changes, report error/retry and a zero-usage selection.
- [ ] Check keyboard-operated selection, light/dark themes and widths 375px, 768px
  and desktop, with no horizontal page scroll.
- [ ] Run npm run test:e2e in both clients. Expect all tests to pass.
- [ ] Review the diff against the spec, report checks and limitations. Commit only
  explicitly approved implementation files once the user authorizes committing.
