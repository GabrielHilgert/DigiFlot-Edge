# DigiFlot Edge — Git-managed installation maintenance

The full `src/install.sh` installs system packages, creates the service account,
clones the repository and creates the Python environment. It should not be
needed again for ordinary UI, backend, browser, launcher or systemd changes.

## One-time migration of an already installed Raspberry Pi

Run these commands **when no experiment is active**:

```bash
sudo digiflot-update
sudo bash /opt/digiflot-edge/src/deploy/migrate.sh
```

The first command is the **existing/legacy** updater: it retrieves the new
deployment sources and restarts the backend once. The second command
transfers the existing service user, port and healthcheck settings to
`/etc/digiflot-edge/install.conf`, installs the managed commands and
synchronizes root-owned systemd units. It does **not** run apt, install pip
requirements, recreate the virtual environment, delete experiments or reset
`src/config.json`.

New installations receive the managed commands automatically from
`install.sh`. Repeat neither the full installer nor the migration in normal
operation.

## Daily commands

| Command | Action |
| --- | --- |
| `sudo digiflot-update` | Fetch/pull Git, synchronize changed services, update pip only if requirements changed and restart the backend only when needed |
| `sudo digiflot-restart` | Restart **only** `digiflot.service` without opening or closing Chromium |
| `sudo digiflot-sync` | Regenerate/synchronize installed services and launchers from Git without fetching updates |
| `digiflot-status` | Show server, health timer and HTTP status |
| `digiflot-edge-open` | Open a single Chromium window in conventional fullscreen (F11 works) |
| `digiflot-browser-autostart enable` | Opt in to opening Chromium after this desktop user's next graphical login |
| `digiflot-browser-autostart disable` | Disable the managed login autostart entry |

`update`, `restart` and `sync` refuse to interfere with active/preparing
experiments by default; `--force` is an explicit override for recovery or
operator-directed maintenance. If an active server does not answer its state
API, these commands fail closed rather than restart blindly.

## Implementation and operational invariants

- The application remains under `/opt/digiflot-edge`; its Git working tree
  and Python virtual environment belong to the unprivileged `digiflot`
  service account.
- Root-owned stable dispatchers reside in `/usr/local/bin` and
  `/usr/local/sbin`. The root maintenance implementation is copied to
  `/usr/local/libexec/digiflot-edge/maintenance.sh` during successful
  synchronization. Subsequent updates can update this copy without a full
  reinstall. The browser launcher runs with **desktop user** privileges.
- Machine-specific settings remain in root-owned
  `/etc/digiflot-edge/install.conf`, not in the Git checkout.
- Unit files are written as root-owned copies under
  `/etc/systemd/system`, **not symlinked into the service-writable Git tree**.
  Relevant changes call `systemctl daemon-reload` and refresh the timer.
- Python source or requirements changes restart the backend; CSS/JS,
  browser and helper-only Git changes normally do not.
- `src/deploy/browser-open.sh` retains an advisory `flock` across the
  Chromium process lifetime and uses a DigiFlot-only profile. Repeated
  shortcut clicks and backend restarts therefore do not open new browser
  tabs/windows. There is no permanent browser-monitoring background service.
- The browser is not launched from `digiflot.service`. Login autostart is
  **opt-in** and applies only to the selected graphical user.

## Configuration and dependencies

Chromium is required for the new desktop launcher. The executable is
detected as `chromium` or `chromium-browser`. Install the appropriate
package for the Pi operating system if neither exists. The launcher does
not silently fall back to another browser (which could create duplicate tabs).

Port/user/watchdog configuration is captured during migration. Changes to
these installation settings can be made by a system administrator in the
root-owned `install.conf`, followed by `sudo digiflot-sync` when Idle.

The backend and Chromium can be restarted independently. Updating or
restarting the backend never opens a new Chromium window.
