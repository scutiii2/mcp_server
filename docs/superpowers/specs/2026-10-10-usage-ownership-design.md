# Usage ownership design

Date: 2026-10-10
Baseline: main at d414983
Status: Draft for review; implementation is not authorized by this planning request.

## Intent and scope

Ember Web Usage shows only the logged-in user's usage, including for administrators.
Ember Admin gains a Usage page with a summary table and selectable per-user details.
The user explicitly selected summary plus details.

Keep the existing personal report features: periods, rolling limits, token/answer/chat
totals, daily activity, annual heatmap, agent/model/provider/gateway breakdown,
recent calls, and Markdown export.

## Approach

Reuse UsageService and the existing report shapes. Add separate admin detail routes;
do not add an account selector to the personal endpoints. This makes authorization
explicit without duplicating aggregation logic.

Moving only the summary table is smaller but does not satisfy the selected scope.
A shared frontend package would add build and ownership work unnecessary for this
change; follow the existing local-copy convention for the two Ember clients.

## Web behavior

- /usage, navigation, and landing-page rules require chat.use.
- Remove the all-accounts request, state, rendering, client method and response type.
- usage.all.view alone no longer grants Web Usage access.
- Personal endpoints continue to derive account_id from the authenticated session.
- Preserve personal charts, limits, periods, breakdowns, recent calls and exports.

## Admin behavior

- Add a top-level /usage page, named usage, requiring usage.all.view.
- Include Usage in ADMIN_PAGES and ADMIN_PERMISSIONS, and in overview descriptions.
  A usage-only account can enter the app and discover Usage without accounts.view.
- Show all existing accounts, including disabled and zero-usage accounts.
- Summary columns: username, tokens, answers, last used in the selected period.
  Order by descending tokens, then username and account_id for stable ties.
- Select a user through a labeled button in the summary row. Initially no user is
  selected; show "Select a user to view their usage." Keep the table visible.
- Show selected-user details below the table, prominently labeled with username.
  Details match the personal report features and use that user's export identity.
- Default to 30 days. Preserve This month, 7 days, 30 days, 90 days, 12 months;
  the heatmap independently requests 366 days.
- Changing period refreshes table and selected report/records; changing grouping
  refreshes the selected report. Changing user reloads report, records and heatmap.
- Immediately clear old user's detail and disable export on user changes. Discard
  stale responses after selection, period, grouping, or logged-in account changes.
  Account changes also clear the summary, selection and annual data.
- Loading is distinguishable from empty data. Summary and main detail errors are
  displayed separately with retry. Recent-call or heatmap failures do not hide the
  main report. Clear stale period data on failure; export only successfully loaded
  data with its loaded user and period labels.
- If a selected account is deleted, clear selection and reload the summary.
- Use existing admin controls, theme/radius tokens and local LineChart component.
  Support keyboard selection and narrow screens without horizontal page scrolling.

## API contract

Existing:
- GET /api/usage -> UsageOut; chat.use; current account only.
- GET /api/usage/records -> list[UsageRecordOut]; chat.use; current account only.
- GET /api/admin/usage -> list[AccountUsageOut]; usage.all.view.

Add:
- GET /api/admin/usage/{account_id} -> UsageOut.
  Same days, since, group_by, agent and provider query validation as /api/usage.
- GET /api/admin/usage/{account_id}/records -> list[UsageRecordOut].
  Same days, since, agent, provider and limit validation as /api/usage/records.

Both new routes require usage.all.view, independently of chat.use or accounts.view.
Authorize before target lookup. Missing target is 404; an existing account with no
usage returns zero/empty results. Reuse windows, report and records with the target
account_id, plus existing response serializers and check_since.

Change all_accounts to an outer join whose selected-period condition is in the
join, so zero-usage accounts remain. Coalesce totals to zero and last_used_at to null.
Align "answers" with personal reports: count distinct non-summary turn_id values.
Tokens include chat and summary usage. Rolling windows are not period-filtered.
UTC period boundaries and local display-time behavior remain as today.

## Constraints and verification

No new permission, dependency, schema migration, upstream service call, or shared
frontend package. Admin sees usage metadata only; this grants no chat-content access.
Keep existing response shapes compatible; document the zero-account inclusion and
answer-count correction. No push or deployment is part of this task.

Prove two-account isolation, permission-only roles, summary/delegation counting,
zero and disabled accounts, invalid dates/IDs/limits, stale responses, account switch,
optional-section failures, correct export labels and responsive keyboard interaction.
Run API tests and both clients' type checks, builds, unit tests and Playwright tests.
