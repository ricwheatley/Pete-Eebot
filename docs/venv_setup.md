# Pete Eebot Virtual Environment Deployment

These steps provision the native Python virtual environment used by the Ubuntu production layout. The pinned dependencies live in `requirements.txt`, so recreating the same environment later is reproducible.

> **Production path:** keep the virtual environment outside the Git checkout at `/opt/myapp/shared/venv`. Docker is used for PostgreSQL only.

---

## 1. Prerequisites

* **Python 3.11.** Install the Ubuntu package or your standard server Python build.
* **python3-venv.** Ensure the venv module is available:
  ```bash
  sudo apt update
  sudo apt install -y python3-venv
  ```
* **Git and build tooling.** Psycopg wheels bundle libpq, so no extra headers are required, but `git` is needed to clone the repo: `sudo apt install -y git`.

---

## 2. Prepare the production directories

```bash
sudo mkdir -p /opt/myapp/releases /opt/myapp/shared /opt/myapp/scripts /opt/myapp/backups/{postgres,secrets,cloud-staging}
sudo chown -R deploy:deploy /opt/myapp
```

Deploy the repository into `/opt/myapp/releases/<release-id>` and point `/opt/myapp/current` at the active release.

---

## 3. Create and activate the virtual environment

```bash
python3 -m venv /opt/myapp/shared/venv
source /opt/myapp/shared/venv/bin/activate
```

The prompt should now show the active environment. To exit later, run `deactivate`.

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
cp /opt/myapp/current/.env.sample /opt/myapp/shared/.env
nano /opt/myapp/shared/.env  # or use your editor of choice
```

At a minimum provide Dropbox, Withings, Telegram, and Postgres credentials. Set `PETEEEBOT_ENV_FILE=/opt/myapp/shared/.env`, `PETEEEBOT_CLI_BIN=/opt/myapp/shared/venv/bin/pete`, and `WITHINGS_TOKEN_FILE=/opt/myapp/shared/runtime/withings/.withings_tokens.json`.

---

## 7. Verify the installation

Run a simple health check before scheduling cron jobs:

```bash
pete status
```

You should see a summary reporting on Postgres, Dropbox, Withings, Telegram, and wger connectivity. If the command is not found, confirm that the virtual environment is active and `~/.local/bin` is on your `$PATH`.

---

## 8. Common operational commands

After activation (`source /opt/myapp/shared/venv/bin/activate`):

```bash
# Run the daily ingest plus summary
pete sync --days 1 && pete message --summary

# Execute the Apple-only ingest
pete ingest-apple

# Trigger the weekly training plan refresh (only 4-week plans are supported)
pete plan --weeks 4
```

Add the commands to cron as documented in the main README once you are satisfied with the manual runs.

Install the scheduler from the repository manifest rather than editing the crontab manually:

```bash
/opt/myapp/current/scripts/install_cron_examples.sh --activate --summary
```

Use `/opt/myapp/current/scripts/install_cron_examples.sh --print` first if you want to inspect the generated crontab before it is applied.

---

## 9. Updating the environment

When new versions of Pete Eebot ship, pull the latest commits and reinstall the editable package. If the dependencies change, update `requirements.txt` (or download the latest copy) and reinstall:

```bash
cd /opt/myapp/current
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
```

---

## 10. Deactivating and removing the environment

```bash
deactivate  # leave the virtual environment session
rm -rf /opt/myapp/shared/venv  # delete the environment entirely
```

This approach leaves your system Python untouched and keeps the deployment footprint isolated from the release checkout.
