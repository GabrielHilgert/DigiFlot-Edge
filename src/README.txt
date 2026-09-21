DigiFlot Edge - boot/service installation
========================================

Files
-----
install.sh
  Main installer. It clones/updates DigiFlot Edge, installs dependencies,
  prepares the venv, installs the systemd service, health-check timer,
  global application launcher, icon and per-user Desktop shortcuts.

launch.sh
  Replacement for src/launch.sh. It understands:
    ./launch.sh             open/start DigiFlot
    ./launch.sh --status    show service/HTTP status
    ./launch.sh --update    update Git + requirements + restart service
    ./launch.sh --foreground

Installation
------------
1. Put install.sh in the directory where DigiFlot-Edge should be installed.
2. If this is an existing repository, replace src/launch.sh with the supplied
   launch.sh (or commit it to the repository before reinstalling).
3. Run:

     chmod +x install.sh
     ./install.sh

Do not run the installer directly as root. It requests sudo only for system
packages and system-wide integration.

Installed system components
---------------------------
/etc/systemd/system/digiflot.service
/etc/systemd/system/digiflot-healthcheck.service
/etc/systemd/system/digiflot-healthcheck.timer
/usr/local/bin/digiflot-healthcheck
/usr/local/bin/digiflot-edge-open
/usr/local/bin/digiflot-status
/usr/share/applications/digiflot-edge.desktop
/usr/local/share/digiflot-edge/<icon>

A DigiFlot Edge.desktop shortcut is also installed for existing interactive
users under /home, and a default shortcut is placed in /etc/skel/Desktop for
future users.

Useful commands
---------------
digiflot-status
sudo systemctl status digiflot
sudo systemctl restart digiflot
journalctl -u digiflot -f
systemctl list-timers digiflot-healthcheck.timer

Health-check behavior
---------------------
- systemd starts DigiFlot automatically at boot.
- If the Uvicorn process exits, Restart=on-failure restarts it after 3 s.
- Every 30 s the health timer sends a local HTTP request.
- If the service is stopped/crashed, the health check starts it.
- If the process remains active but HTTP fails twice consecutively, the
  health check restarts the service.
- The initial health check waits 90 s after boot to avoid interfering with
  normal Raspberry Pi startup.

Environment overrides
---------------------
DIGIFLOT_INSTALL_BASE        installation parent directory (default: cwd)
DIGIFLOT_BRANCH              Git branch (default: main)
DIGIFLOT_PORT                local port (default: 8000)
DIGIFLOT_HEALTH_INTERVAL     timer interval (default: 30s)
DIGIFLOT_HEALTH_BOOT_DELAY   first boot check (default: 90s)
DIGIFLOT_HEALTH_MAX_FAILURES failures before restart (default: 2)
