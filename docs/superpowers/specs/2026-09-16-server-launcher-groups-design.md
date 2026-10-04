# Server Launcher Groups Design

## Goal

Make server-launch configurations reusable. Users can capture a working set
of live launcher instances as a named group, then later start that exact set
from one place without recreating each server configuration manually.

## Scope

- Move the Servers and Instances tabs into a global tab bar above the sidebar
  and main panel; add Groups as a third global tab.
- Add named, persistent groups of active launcher instances.
- Let users create a group from Instances, inspect it in Groups, start all of
  its members, and delete its saved definition.

Out of scope: editing a group in place, stopping a group as a unit, and
starting a partially valid group.

## Navigation and layout

The top-level window has a three-item global tab bar: Servers, Instances,
and Groups. The sidebar and main panel remain below the tab bar.

Instances keeps its current list and detail/log view. Its sidebar actions
include Create Group, Clear Closed, Kill Instances, and Refresh. Create Group
is available only on this tab.

Groups uses the sidebar to list saved group names. Selecting a group renders
its members and their saved launch configuration in the main panel, alongside
Start All and Delete controls.

## Group model and persistence

Groups are stored in `server_launcher/groups.json`, independently of presets.
The file contains a mapping from a unique group name to an ordered list of
launch snapshots. A snapshot preserves:

- template key;
- requested port;
- extra environment variables;
- extra command-line arguments; and
- preset name, if the original instance was launched from a preset.

Snapshots intentionally permit the same template key more than once when
ports or other launch options differ. A group is a recipe, not a reference to
the original live Instance object.

## Creating and replacing groups

Create Group opens a dialog that accepts a name and presents checkboxes for
every currently live tracked instance. Closed and failed instances are not
available for selection. Saving requires a non-empty name and at least one
member.

Group names are unique. Saving a name that already exists prompts the user to
confirm replacement before overwriting that group's stored recipe.

## Starting a group

Start All is all-or-nothing at preflight time:

1. Resolve every stored template key against the current discovered templates.
2. Ensure every requested port is free.
3. If any template is unavailable or any port is occupied, show every blocker
   and start no member.
4. If validation succeeds, create tracked Instances using each snapshot's
   exact configuration.

Starting uses the existing instance-launch mechanism. Consequently, bootstrap,
live status, logs, Stop/Restart, and Clear Closed remain owned by Instances.
Preflight cannot guarantee a boot will later succeed; individual asynchronous
launch failures surface through those normal instance statuses and logs.

If a live process already occupies a group's saved port, including one already
tracked by this launcher, it is a blocker. The group is not partially started
and no attempt is made to assign alternate ports.

## Deleting groups

Delete requires confirmation. It removes only the saved group recipe and
never stops, restarts, or otherwise changes any live instance.

## Errors and empty states

- Empty Groups displays a dedicated empty state.
- A missing template is shown as unavailable in group details and blocks
  Start All.
- Occupied ports are named in the Start All validation feedback.
- Invalid or unreadable `groups.json` is treated as no saved groups, matching
  the launcher's existing preset-file resilience.

## Verification

Focused tests will cover group-file loading/saving, snapshots retaining exact
launch options, replacement behavior, and all-or-nothing preflight. Existing
instance and preset tests remain green. A syntax compilation and diff
whitespace check complete the verification.
