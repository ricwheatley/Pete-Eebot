# Credential Exposure Incident Runbook

Use this runbook when a credential, runtime token file, or secret-bearing blob is committed or emitted by CI. Keep the incident open until credential invalidation, history cleanup, fresh-clone validation, and cache/fork coordination all have evidence.

Never paste a credential or a fragment of one into an issue, pull request, commit message, chat, terminal command, or incident note. Record provider, credential name, owner, timestamp, action, and pass/fail result only. Use provider UIs, a password manager, protected environment files, and commands that read values from environment variables or standard input.

## Required order

1. Freeze pushes and scheduled deployments long enough to obtain a stable remote-ref inventory.
2. Revoke or rotate every exposed credential and deploy the replacements.
3. Verify the old credentials are unusable without printing them.
4. Rewrite a fresh mirror clone, validate it, and obtain owner approval for the exact force-push targets.
5. Force-push the controlled refs, delete risky Actions runs/artifacts, and ask GitHub Support to remove cached views and pull-request references.
6. Replace old clones and coordinate any forks or mirrors so tainted history cannot be reintroduced.

History cleanup never substitutes for rotation: copies may already exist outside GitHub.

## Pete-Eebot incident inventory

Treat the following as exposed until provider-side invalidation is recorded:

- Withings access/refresh token chains previously stored in `.withings_tokens.json` and `docs/raw/withings_token.json`.
- The DuckDNS account token historically embedded in `pete_e/infrastructure/cron_manager.py` and `pete_e/resources/pete_crontab.csv`.
- Credentials referenced by the deleted `reveal-secret.yml` workflow: `GH_SECRETS_TOKEN`, `WITHINGS_CLIENT_SECRET`, `WITHINGS_REFRESH_TOKEN`, `TELEGRAM_TOKEN`, `WGER_API_KEY`, and the legacy `JEFIT_USERNAME`/`JEFIT_PASSWORD`. The Telegram chat identifier is not an authentication secret, but its exposure should still be recorded as account metadata disclosure.
- Any additional credential reported by the full-history Gitleaks scan or GitHub secret-scanning alerts.

The deleted reveal workflow had successful public Actions runs named `Reveal Secrets` and `Reveal Secrets via Artifact` on 13 September 2025. Do not open or download their logs/artifacts into routine tooling. Delete the runs through the Actions UI after recording only their run IDs and deletion timestamps in the private incident record.

Audit snapshot from 17 August 2026: the public remote advertised one owner-controlled branch (`main`) and no tags, with no open pull requests, GitHub-network forks, or releases. A fresh mirror also received 184 read-only pull-request refs, and every one was reachable from at least one identified credential-bearing commit. Re-count all of these immediately before cleanup; the snapshot is not a substitute for the pre-rewrite manifest.

## 1. Contain and inventory

- Name an incident owner and a separate reviewer for the destructive rewrite.
- Pause pushes, merges, deploy webhooks, scheduled workflows, and automated Git writers.
- Record `git ls-remote --heads --tags origin` immediately before the rewrite. Compare it with the approved target list.
- Review repository branches, tags, pull requests, releases, Actions runs/artifacts/caches, Pages deployments, forks, mirrors, package releases, and backup archives.
- Preserve one restricted, encrypted incident copy only if policy requires it. A tainted backup contains the credentials and needs an owner and destruction date.
- Do not use an old clone as the rewrite source.

## 2. Rotate and verify credentials

### GitHub token and Actions secrets

1. Identify what `GH_SECRETS_TOKEN` represented. Delete the matching fine-grained or classic personal access token under **GitHub account Settings > Developer settings > Personal access tokens**. If it was an OAuth or GitHub App token, revoke the relevant authorization instead.
2. Create a least-privilege, expiring replacement only if the integration still needs one. Prefer a GitHub App or the workflow-scoped `GITHUB_TOKEN` over a long-lived personal token.
3. In **Repository Settings > Secrets and variables > Actions**, remove every obsolete secret and replace only those still required. The API cannot reveal old values; rotation must occur at each provider.
4. Verify the old token returns an authentication failure and the replacement can perform only its intended operation. Record HTTP/result status, not response bodies or token material.

### DuckDNS

1. Sign in to the [DuckDNS account page](https://www.duckdns.org/) using the account owner identity. Use the provider's account-token replacement control if it is available. If the account cannot issue a replacement token, create a new account credential, recreate or transfer the required domains, and then disable/delete the old account credential.
2. Update `DUCKDNS_TOKEN` only in the protected production environment file and any approved secret manager. Do not edit the cron CSV; it already expands the environment variable.
3. Restart or reload the cron environment. Make one HTTPS update with the replacement and confirm the provider returns success.
4. From an isolated shell that reads the retained old value from a password manager, make the same non-destructive update request and confirm the provider rejects it. Destroy the retained old value after recording the result.

DuckDNS documents the update API and confirms that the account token authorizes DNS changes. A successful new-token update is not proof that the old token was invalidated; perform the negative check.

### Withings

1. In the Withings app, open **Profile > Apps**, select the Pete-Eebot integration, and disconnect it. The web-dashboard alternative is **Profile > User > Settings > Manage My Partners > Disconnect > Confirm**.
2. Rotate the Withings application client secret in the developer dashboard because the deleted reveal workflow referenced it. Update only the protected environment/secret manager.
3. Remove the old runtime token file from the host's external runtime directory after preserving only the minimum restricted evidence required by policy.
4. Re-authorize with `pete withings-auth`, exchange the short-lived code with `pete withings-code`, and run `python -m scripts.check_auth`. Token values are saved to `WITHINGS_TOKEN_FILE` and must not be displayed.
5. Verify that the disconnected token chain fails a non-destructive provider authentication check. Withings documents that access tokens are short lived and rotated refresh tokens have a limited overlap, so merely obtaining a new chain is not immediate proof that every old token is unusable.

### Telegram, wger, and legacy Jefit

- Revoke the Telegram bot token through `@BotFather`, issue a new token, update the protected runtime/GitHub secret locations, restart the listener, and confirm the old token fails a harmless Bot API identity call.
- Revoke/regenerate the wger API key in the account API settings, update approved secret locations, and verify old-key rejection plus a read-only request with the new key.
- Change the legacy Jefit account password, terminate other sessions where supported, enable MFA if available, and remove the GitHub secret entirely if the integration is retired.

## 3. Prepare the history rewrite

The required tool is `git-filter-repo` 2.47 or newer because that release line supports `--sensitive-data-removal`.

1. Obtain reviewer sign-off that rotation evidence exists and the push freeze is active.
2. Create a fresh mirror clone in a restricted temporary directory.
3. Create a mode-0600 replacement-expression file outside the clone. It must contain one `literal:` mapping for every distinct historical DuckDNS token discovered by the private incident scan. Populate it from the restricted inventory without terminal output. Never commit it.
4. Capture the pre-rewrite heads/tags manifest and the current default-branch SHA.
5. Run the rewrite only in the disposable mirror:

```bash
git filter-repo --sensitive-data-removal \
  --invert-paths --path .withings_tokens.json \
  --path docs/raw/withings_token.json \
  --replace-text ../duckdns-replacements.txt
```

6. Securely delete the replacement-expression file after the rewrite validation completes.
7. Review `.git/filter-repo/changed-refs`, the reported first changed commits, affected pull-request refs, LFS orphan report, branch/tag counts, and commit-count changes. Stop if an unexpected ref or path changed.

Do not run this command in the normal development checkout. `--sensitive-data-removal` performs an all-ref fetch and intentionally rewrites commit IDs.

## 4. Validate before the force-push

All commands must use full redaction and must not upload reports as public CI artifacts.

```bash
gitleaks git --redact=100 --config .gitleaks.toml --log-opts="--all" .
git rev-list --objects --all -- .withings_tokens.json docs/raw/withings_token.json
git for-each-ref --format='%(refname) %(objectname)'
```

Expected results:

- Gitleaks exits successfully with no findings.
- The Withings token-file object query prints nothing for either historical path.
- The ref set exactly matches the approved heads/tags plus any expected read-only pull-request refs.
- A private equality check against the incident inventory finds none of the original values in any reachable blob. Output only the match count.

Inspect the rewritten versions of both DuckDNS paths and confirm they contain environment-variable expansion or non-usable placeholders, not literal tokens.

## 5. Push and clean GitHub

1. Re-run `git ls-remote --heads --tags origin`. If it differs from the frozen manifest, stop and reconcile the new work.
2. Temporarily allow the approved force-push if branch protection blocks it.
3. With two-person confirmation of the repository URL and ref manifest, push the rewritten mirror:

```bash
git push --force --mirror origin
```

Failures for GitHub's read-only `refs/pull/*` are expected; any branch/tag failure is not.

4. Restore branch protection immediately. Require the `Secret scan` check before merge.
5. Delete the two historical reveal-workflow runs and any retained artifact through **Actions > run > ... > Delete workflow run**. Review other runs from the exposure window before deletion; never download suspected secret-bearing artifacts to an ordinary workstation.
6. Open a [GitHub Support request](https://support.github.com/) using the repository name, affected pull-request count, first changed commits, and any LFS orphan report. Ask Support to dereference affected pull requests, run server garbage collection, and remove cached views.
7. In **Settings > Advanced Security**, enable Secret Protection, secret scanning, generic-pattern scanning where offered, and push protection. Review all alerts; do not dismiss a provider finding until rotation evidence exists.

## 6. Validate from a genuinely fresh clone

After the remote rewrite and GitHub cleanup, use a new directory and clone from GitHub, not from a local object store:

```bash
git clone --mirror https://github.com/ricwheatley/Pete-Eebot.git fresh-verification.git
git --git-dir=fresh-verification.git rev-list --objects --all -- \
  .withings_tokens.json docs/raw/withings_token.json
```

Extract `.gitleaks.toml` from rewritten `main` to a temporary non-secret file, then run Gitleaks against the mirror with `--log-opts="--all"` and `--redact=100`. Confirm the original-value equality scan reports zero. Separately make a normal fresh checkout and run:

```bash
python scripts/test_secret_scanner.py
pytest -q
```

Record the fresh-clone remote URL, timestamp, ref counts, tested commit SHA, scanner version, and pass/fail results.

## 7. Forks, clones, caches, and collaborators

- GitHub-network fork count is only evidence about visible forks at query time. It does not cover detached forks, private mirrors, downloaded archives, or old clones.
- Every collaborator must discard and freshly clone the repository. If preservation is essential, follow the `git-filter-repo` cleanup guidance and rebase clean commits; never merge an old branch into rewritten history.
- Ask mirror and fork owners to purge all affected refs or delete/recreate the copy. An owner cannot rewrite another user's fork or clone.
- Invalidate deployment checkouts, CI caches, Pages/source archives, release assets, package artifacts, backups, and exported ZIP/tar archives that may contain the old objects.
- Keep provider credentials revoked permanently. Purging the central repository cannot recall copied values.

## Closure record

The incident is closed only when all of the following are attached to the private record:

- Provider-side rotation/revocation and old-credential rejection evidence for every affected credential.
- Pre/post rewrite ref manifests and reviewer approval.
- All-ref scanner result and original-value equality count of zero.
- Fresh remote clone validation result.
- Reveal-workflow run deletion and GitHub Support case reference.
- Fork/mirror/collaborator acknowledgements and old-clone replacement status.
- GitHub Secret Protection/push-protection status and passing `Secret scan` check.
