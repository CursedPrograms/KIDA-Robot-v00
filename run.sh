#!/bin/bash
# run.sh - starts KIDA. By hand, from the desktop, or by her service (start_service.sh).
#
#   * The first time it's run by hand and her service isn't installed yet, it installs it
#     (install_service.sh, asks for your password once): from then on she starts at boot, and this
#     window hands over to the service.
#   * Her packages: the venv is made the first time, and requirements.txt installed again
#     whenever it changes.
#   * Esc in her window closes her and she starts again here (as KIDA-01); Q quits for good.
#   * The whole run is logged: logs/run.log (this run, from the start), logs/run.prev.log (the one
#     before). Her web server shows it at /logs (/logs?prev=1).

# Run from the repo root no matter where this is launched from
# (desktop shortcut, autostart, ssh), so relative paths in the scripts resolve.
cd "$(dirname "$(readlink -f "$0")")" || exit 1

# Her venv: venv/ (where her packages are), or psdenv/ on a Pi that only has that one. A venv without
# pip (Debian makes one like that when its venv module can't set pip up) is useless: it's made again.
VENV_DIR="venv"
[ ! -x venv/bin/python ] && [ -x psdenv/bin/pip ] && VENV_DIR="psdenv"
SERVICE_FILE="/etc/systemd/system/kida.service"

# ---- First run by hand: make her a service (once; .service_offered remembers it was tried)
if [ -z "$INVOCATION_ID" ] && [ ! -f "$SERVICE_FILE" ] && [ ! -f .service_offered ] && command -v systemctl >/dev/null; then
    echo "KIDA isn't set up to start at boot yet: installing her service (install_service.sh) ..."
    [ -t 0 ] && touch .service_offered   # asked you (in a terminal): not again, whatever you answered
    if { [ -t 0 ] && sudo bash ./install_service.sh; } || sudo -n bash ./install_service.sh 2>/dev/null; then
        echo "Her service is running now (it started her): this window can close."
        echo "Live log: journalctl -u kida -f, or http://<her IP>:5003/logs"
        exit 0
    fi
    echo "(Couldn't install the service. Later: sudo ./install_service.sh)"
fi

# ---- Only one KIDA at a time: the service and a run.sh started by hand (or twice) would fight over
# the camera and the GPIO, and both crash. The second one says so and leaves.
exec 9>"/tmp/kida.lock"
if ! flock -n 9; then
    echo "KIDA is already running (her service, or another run.sh). Stop it first:"
    echo "  sudo systemctl stop kida      (the service)"
    exit 1
fi

# ---- The log of the whole run, from here on: her package installs too
mkdir -p logs
[ -f logs/run.log ] && mv -f logs/run.log logs/run.prev.log
LOG_FILE="logs/run.log"
echo "=== run.sh started at $(date) in $(pwd), as $(whoami) ===" >> "$LOG_FILE"

# Check if the virtual environment directory exists
if [ -d "$VENV_DIR" ] && [ ! -x "$VENV_DIR/bin/pip" ]; then
    echo "=== $VENV_DIR has no pip: making it again ===" | tee -a "$LOG_FILE"
    rm -rf "$VENV_DIR"
fi
if [ ! -d "$VENV_DIR" ]; then
    # Create the virtual environment and install what KIDA needs.
    # --system-site-packages: picamera2 comes from apt (see gpio-requirements.txt)
    # and isn't installable with pip, so the venv has to see the system packages.
    python3 -m venv --system-site-packages "$VENV_DIR" 2>&1 | tee -a "$LOG_FILE"
fi
# (Re)install whenever requirements.txt changed since the last install, so a new one (like bleak)
# reaches an existing venv too. The copy in the venv remembers what was installed. pip installs a file
# all or nothing: if one package won't build here (rpi-ws281x, spidev, opencv on a new Python), none of
# them land and she can't start. So if the whole file fails, each package is tried on its own, and the
# log says which ones didn't make it.
if ! cmp -s requirements.txt "$VENV_DIR/requirements.installed"; then
    echo "=== Installing KIDA's Python requirements ===" | tee -a "$LOG_FILE"
    if "$VENV_DIR/bin/pip" install -r requirements.txt 2>&1 | tee -a "$LOG_FILE"; [ "${PIPESTATUS[0]}" -eq 0 ]; then
        cp requirements.txt "$VENV_DIR/requirements.installed"
    else
        failed=""
        while read -r pkg; do
            pkg="${pkg%%#*}"; pkg="$(echo "$pkg" | tr -d '[:space:]')"
            [ -z "$pkg" ] && continue
            "$VENV_DIR/bin/pip" install "$pkg" >> "$LOG_FILE" 2>&1 || failed="$failed $pkg"
        done < requirements.txt
        if [ -z "$failed" ]; then
            cp requirements.txt "$VENV_DIR/requirements.installed"
        else
            echo "=== These packages didn't install:$failed (the rest did; see above for why) ===" | tee -a "$LOG_FILE"
        fi
    fi
fi

# Audio: force ALSA on the card that `speaker-test -D hw:0,0` plays through
# (read by scripts/music_player.py). Override per run, e.g.
#   KIDA_AUDIO_DEVICE=plughw:0,0 ./run.sh
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-alsa}"
export KIDA_AUDIO_DEVICE="${KIDA_AUDIO_DEVICE:-hw:0,0}"
export PYTHONUNBUFFERED=1   # her log line by line, as it happens

# Activate the virtual environment and run her; Esc brings her back, Q (exit code 99) ends it
source "$VENV_DIR/bin/activate"
trap 'echo; echo "=== Stopped with Ctrl+C ===" >> "$LOG_FILE"; exit 130' INT   # Ctrl+C in the terminal: stop, don't restart
while true; do
    echo "=== KIDA starting at $(date) ===" | tee -a "$LOG_FILE"
    python run.py 2>&1 | tee -a "$LOG_FILE"
    code=${PIPESTATUS[0]}
    if [ "$code" -eq 99 ]; then
        echo "=== Quit with Q at $(date): not starting her again ===" | tee -a "$LOG_FILE"
        break
    fi
    echo "=== KIDA stopped (exit code $code) at $(date): starting again in 3 s (Q in her window quits for good) ===" | tee -a "$LOG_FILE"
    sleep 3
done
