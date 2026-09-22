# Protected main data writers

Status: Draft implementation for C-118 / Issue #177. Do not activate PR #176 until this control plane is configured and validated.

## Why this exists

The repository has generated-data workflows that legitimately commit to `main`. Strong protection for PR #176 cannot safely grant a broad bypass to the general GitHub Actions token, because any future `contents: write` workflow on trusted main would inherit that path.

C-118 separates that authority into one repository-scoped deploy key. The private key is available only to jobs referencing the `main-data-writer` Environment, every writer job is hard-gated to `refs/heads/main`, and the normal `GITHUB_TOKEN` is read-only.

Repository rulesets support bypass actors including deploy keys. The intended ruleset bypass is the dedicated data-writer deploy key only, in **Always** mode, not the general `github-actions` App and not the Owner account.

## Code-side controls

Every workflow containing `git push` must:

- use `permissions: contents: read`;
- run only when `github.ref == 'refs/heads/main'`;
- reference Environment `main-data-writer`;
- use pinned `actions/checkout` with `secrets.MAIN_DATA_WRITER_DEPLOY_KEY`;
- scope any `push:` trigger to `branches: [main]`.

`tests/test_main_data_writer_security.py` fails closed if a self-pushing workflow violates these rules or a new writer appears without explicit review.

## Owner setup order

Do these steps while PR #176 remains disabled.

1. Create a new SSH deploy-key pair dedicated only to generated-data writes. Do not reuse a personal SSH key.
2. In repository Settings → Deploy keys, add the **public** key with write access. Keep the private key off the repository.
3. Create Environment `main-data-writer`.
   - Restrict deployment branches to `main` only.
   - Add Environment secret `MAIN_DATA_WRITER_DEPLOY_KEY` containing the private key.
   - Do not add required reviewers; scheduled writers must run unattended.
4. Create Environment `owner-main-approval`.
   - Add the Owner as required reviewer.
   - Leave **Prevent self-review** off, because AI-created PRs are attributed to the Owner account and the Owner must be able to perform the explicit UI approval.
   - Store no secrets in this environment.
5. After C-118 code is reviewed, merge it while the old main is still writable. Immediately confirm at least one harmless writer run can commit using the deploy key.
6. Create an **Active** branch ruleset targeting only `main`:
   - require changes through pull requests;
   - require successful deployment to `owner-main-approval` before merge;
   - block force pushes and deletions;
   - add the dedicated data-writer deploy key as the bypass actor with bypass mode **Always** (generated-data writers must push directly to `main`);
   - do **not** add the Owner account or the general `github-actions` App as bypass actors;
   - do not enable required signed commits unless generated-data commit signing is separately implemented and verified.
7. Verify:
   - a normal direct push to `main` is rejected;
   - a generated-data writer can still update `main`;
   - a ready-for-review PR waits on `owner-main-approval`;
   - pushing a new PR head cancels the older approval wait and requires a fresh approval;
   - after approval, the deployment succeeds for the exact latest head.
8. Only then proceed with PR #176 Environment/token setup and its harmless V2 end-to-end test.

## Rollback

If data writers fail after protection is enabled:

- keep PR #176 disabled;
- disable the main ruleset temporarily only under Owner control;
- do not grant broad `github-actions` bypass as a shortcut;
- inspect the `main-data-writer` Environment branch restriction, deploy-key write permission, checkout authentication, and Actions logs;
- restore protection after the dedicated writer path is verified.

The deploy key can write repository content. Treat its private half like a production credential and rotate/revoke it if exposure is suspected.
