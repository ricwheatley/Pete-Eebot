# Pete Eebot Virtual Environment Deployment

These steps provision a lightweight Python virtual environment that runs Pete Eebot natively on a Raspberry Pi (or any Linux host) without the memory overhead of Docker. The pinned dependencies live in `requirements.txt`, so recreating the same environment later is reproducible.

> **Recommended path:** The virtual environment install keeps the idle footprint below 100 MB on a Raspberry Pi 4, while still exposing the same CLI entry points as the container image.

---

## 1. Prerequisites

* **Python 3.11.** Raspberry Pi OS (Bookworm, 64-bit) ships 3.11 by default. If you are on Bullseye, install `python3.11` from `pipx` or the `deadsnakes` PPA first.
* **python3-venv.** Ensure the venv module is available:
  ```bash
  sudo apt update
  sudo apt install -y python3-venv
  ```
* **Git and build tooling.** Psycopg wheels bundle libpq, so no extra headers are required, but `git` is needed to clone the repo: `sudo apt install -y git`.

---

## 2. Clone the repository

```bash
cd /home/pi
git clone https://github.com/your-org/Pete-Eebot.git
cd Pete-Eebot
```

Replace `/home/pi` with the directory you want to deploy into. All subsequent commands assume the repository root.

---

## 3. Create and activate the virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

The prompt should now show `(.venv)` as a prefix. To exit later, run `deactivate`.

If you prefer a system-wide location (for example, `/opt/pete-eebot`), adjust the path in the `python3 -m venv` command.

---

## 4. Install the pinned dependencies

Upgrade `pip` so it understands the newest wheel tags, then install the reproducible lock file:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The packages ship binary wheels for Linux `aarch64`, so the install completes without compiling C extensions even on a Pi.

---

## 5. Install the Pete Eebot package

With the dependencies in place, install the local package so the `pete` CLI entry point is registered:

```bash
python -m pip install --no-deps -e .
```

The `--no-deps` flag keeps the previously pinned versions intact. Use `pip install .` instead if you are not modifying the source tree and prefer an immutable install.

---

## 6. Configure environment variables

Copy the sample environment file and fill in your integration secrets:

```bash
cp .env.sample .env
nano .env  # or use your editor of choice
```

At a minimum provide Dropbox, Withings, Telegram, and Postgres credentials. The Typer commands automatically load the `.env` file when it resides in the project root.

---

## 7. Verify the installation

Run a simple health check before scheduling cron jobs:

```bash
pete status
```

You should see a three-line summary reporting on Postgres, Dropbox, and Withings connectivity. If the command is not found, confirm that the virtual environment is active and `~/.local/bin` is on your `$PATH`.

---

## 8. Common operational commands

After activation (`source .venv/bin/activate`):

```bash
# Run the daily ingest plus summary
pete sync --days 1 && pete message --summary

# Execute the Apple-only ingest
pete ingest-apple

# Trigger the weekly training plan refresh (only 4-week plans are supported)
pete plan --weeks 4
```

Add the commands to cron as documented in the main README once you are satisfied with the manual runs.

---

## 9. Updating the environment

When new versions of Pete Eebot ship, pull the latest commits and reinstall the editable package. If the dependencies change, update `requirements.txt` (or download the latest copy) and reinstall:

```bash
git pull
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
```

---

## 10. Deactivating and removing the environment

```bash
deactivate  # leave the virtual environment session
rm -rf .venv  # delete the environment entirely
```

This approach leaves your system Python untouched and keeps the deployment footprint minimal, ideal for memory-constrained devices such as the Raspberry Pi.
