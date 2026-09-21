DigiFlot Edge shared system installer v3



Install;

curl -fsSL https://raw.githubusercontent.com/GabrielHilgert/DigiFlot-Edge/main/src/install.sh -o install.sh
chmod +x install.sh
./install.sh


========================================

Installation layout
-------------------
The repository is now ALWAYS installed at:

  /opt/digiflot-edge

The directory where install.sh is downloaded/executed is irrelevant. The
installer no longer reuses an arbitrary checkout under /home and cannot clone
DigiFlot-Edge inside another DigiFlot src/ directory.

Why /opt?
---------
/opt is the conventional location for a self-contained machine-wide
application. All Linux users use the same running DigiFlot instance through:

  http://127.0.0.1:8000

Users do not need their own copy of the repository or Python environment.

Service account
---------------
The server runs as the Linux user "digiflot" by default. If that account
already exists, it is reused. Otherwise the installer creates a system
account with home /var/lib/digiflot-edge.

The service account is added to the available hardware groups:

  video
  i2c
  dialout

This account owns /opt/digiflot-edge and the .venv so that camera, I2C, serial,
configuration and experiment output access remain controlled by one process.

Desktop access
--------------
The installer creates a launcher for every existing interactive /home user and
places another copy in /etc/skel/Desktop for future users. The launcher does
not reference /opt directly; it simply opens the shared local web server.

Install / update all integration
--------------------------------
Run from any directory:

  chmod +x install.sh
  ./install.sh

The result is always /opt/digiflot-edge.

Normal updates
--------------
After installation:

  sudo digiflot-update

This checks Git in /opt/digiflot-edge. If no update is needed it prints that
nothing changed and does not restart the service. If an update is applied it
refreshes Python requirements and restarts DigiFlot.

Status / logs
-------------
  digiflot-status
  systemctl status digiflot
  journalctl -u digiflot -f
  systemctl list-timers digiflot-healthcheck.timer

Repair only the main service file
---------------------------------
  ./repair-systemd.sh

This repair tool intentionally uses /opt/digiflot-edge and will refuse to use
an old /home/... checkout.

Repository launch.sh
--------------------
The included launch.sh is intended to replace src/launch.sh in Git. It keeps
foreground mode for debugging, but normal operation uses systemd. Its
--update option delegates to the global shared updater.
