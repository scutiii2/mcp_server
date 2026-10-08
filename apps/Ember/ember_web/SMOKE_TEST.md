# ember_web smoke test against the real ember_api

The unit and e2e tests (`npm test`, `npm run test:e2e`) answer every `/api` call
with a fake. This checklist is what they cannot prove: the same screens working
against the real ember_api, with real saves, real deletes and the real
permissions. Run it by hand after a change to the Settings page, the Danger zone,
the confirmation dialogs or the admin screens. It takes about 15 minutes.

## Before you start

Use a throwaway setup, not your own account. Several steps delete things.

1. Start the stack: `server_launcher` (the "Ember" group) or, one by one,
   `mcp_server`, `ai_agent`, `ember_api` (port 8030) and `ember_web`
   (`run.bat`, port 5173). Open `http://127.0.0.1:5173`.
2. Log in as the bootstrap admin. If `BOOTSTRAP_ADMIN_PASSWORD` is empty, the
   random password was printed in ember_api's console on its first start.
3. Make two throwaway members. For each: Admin > Invites > create an invite
   (manual), copy the code (it is shown once), log out, and register at
   `/register` with it. Call them `smoke-a` and `smoke-b`. If email verification
   is on and no SMTP is set up, turn it off (`require_email_verification: false`
   in ember_api's config) or use a verified account.
4. Log back in as the admin and, in Admin > Roles, create a throwaway role named
   `smoke-role`. Give `smoke-b` that role (Admin > Accounts > `smoke-b` > Add role).

Do not write real passwords into this file or into notes.

## 1. Settings page (log in as `smoke-a`)

- [ ] The gear in the nav rail opens `/settings`. There is no Administration group.
- [ ] Search `dark mode` shows only Theme. Search `zzz` says nothing matches, and
      "Clear search" brings everything back.
- [ ] Turn on Terse replies: a dot, a reset icon and "1 modified" appear. Reload:
      all three are still there (saved in this browser).
- [ ] Theme Dark changes the page at once; its reset goes back to System.
- [ ] Reset Terse replies: the dot and the badge go away.
- [ ] In the chat, the gear menu shows the same Terse replies state and has an
      "All settings" link.

## 2. Tool approval (log in as the admin)

- [ ] Settings shows Administration > Tool approval with "Applies to all accounts".
- [ ] Flip it on: the unsaved bar appears and nothing has changed yet. Cancel
      drops it.
- [ ] Flip it on and Save: "Saved" shows and the setting counts as modified.
      Reload: it is still on.
- [ ] As `smoke-a` (another browser or a private window): in Settings,
      "Ask before tools" is locked on, with the note that an administrator
      requires approval.
- [ ] Back as the admin: "Back to default" makes a draft; Save turns it off.
      **Leave it off when you finish.**

## 3. Confirmations that delete (log in as `smoke-a`, then the admin)

- [ ] Make three chats. Delete one from its menu: a dialog asks, Cancel keeps
      it, Delete removes it. Reload: it stays gone.
- [ ] "Delete all chats": the field is focused, Delete stays locked until
      `delete all` is typed exactly (10/10), then it deletes the remaining chats.
- [ ] As admin, Admin > Roles > `smoke-role` (still held by `smoke-b`): Delete
      role opens a dialog that needs `smoke-role` typed. Cancel it. Make a second
      role that no account holds and delete it: no typing, the button is ready at
      once. The protected Administrator role has no Danger zone.
- [ ] Admin > Accounts > `smoke-b`: Delete account is in the red Danger zone. The
      dialog needs `smoke-b` typed. After deleting, the row is gone and the
      Accounts count drops. The bootstrap admin's drawer has no Danger zone.
      `smoke-role` now holds no account, so deleting it needs no typing.
- [ ] Share a chat, then "Turn off" its link: a dialog opens over the share
      dialog; Cancel keeps the link, confirming revokes it. The old link no longer
      opens.
- [ ] Save a prompt, open Saved prompts > Manage, delete it: the dialog asks first.
- [ ] Edit your first question in a chat that has later messages: it asks before
      dropping them. Cancel keeps the edit open.

## 4. Capability switch (admin; affects every mcp_server client)

- [ ] On Capabilities, pick a harmless capability. Turn it off: the dialog has the
      danger style; the card shows "off" and its tools disappear for everyone.
- [ ] Turn it back on: a plain dialog; the tools return. **Leave it on.**

## 5. Small layout checks

- [ ] Phone width (375 px): the account drawer in Admin is a sheet above the nav
      bar, and "Delete account" is not hidden behind it.
- [ ] Account page: the Devices rows stay inside their card.
- [ ] Light and dark both look right on Settings and the Danger zone.

## After the run

- Tool approval is off, the capability is on, and `smoke-role` and any other
  extra role are deleted.
- Remove `smoke-a` (Admin > Accounts, type its name) and any unused invites.

## If something fails

Note the step, the exact text of any error, and the request that failed
(browser dev tools > Network). A step that works in the e2e test but fails here
means the fake `e2e/fakeApi.ts` no longer matches ember_api: fix the route or the
fake, and add the missing case to the e2e suite.
