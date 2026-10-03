# Deploy, back up and recover

[English](deployment.md) · [简体中文](zh-CN/deployment.md) · [日本語](ja/deployment.md)

Run one backend writer process for each data directory. Use a dedicated project environment and keep runtime data in a writable workspace. Model services can run on other machines; configure URLs reachable from the backend.

```bash
narraloom serve --workspace /path/to/my-game   --models-config /path/to/models.local.json   --web-dist /path/to/NarraLoom/web/dist   --host 127.0.0.1 --port 18090
```

Omit `--web-dist` for API-only use. Paths resolve relative to `--workspace`; explicit absolute paths are supported. `--data-root`, `--output-root` and `--secrets-root` let a host choose separate storage. The default runtime directories are `data`, `outputs` and `secrets`.

## Access and identity

The built-in session cookie identifies a browser's library and campaigns. Keep it when returning to the same server. Export campaign backups before clearing browser data. The Python SDK saves its session in a private file. Use the same hostname and port when resuming saved requests.

The current deployment model is an individual or trusted-group server. For remote access, use an SSH tunnel or an authenticated HTTPS reverse proxy under one origin. Keep provider keys in private environment variables, a service secret store or files inside `secrets_root`.

## Backups

Use the campaign backup/download and restore UI or API to move an adventure between sessions. Backups include its full creator state, including secrets. Native world packages share reusable content; player notes export only the visible playthrough.

For a full-instance snapshot, stop its writer gracefully and copy the workspace's data and referenced asset directories together. Keep model configurations/secrets separately. Restore into an isolated workspace first, using a compatible framework version, and check `/healthz` and representative campaigns before switching traffic.

## Recovery

Refresh or poll an existing job after a browser/network interruption. A local timeout leaves server work running. Reuse the original request ID; explicit retry continues eligible failed/interrupted work. Restarted incomplete jobs expose an interrupted state. A `recovery_required` error calls for storage recovery and receipt inspection.

Avoid sharing a live data directory between backend processes. The journal lock enforces one writer. `GET /healthz` checks application/storage readiness; model connection checks are separate. Logs and model traces live under the configured output directory.

| Symptom | Check |
| --- | --- |
| Model unavailable or 401 | Backend-visible endpoint, exact model ID and key variable/file |
| Invalid structured response | Provider JSON mode, model capability, output limit and task report |
| Story test fails | Report's source text, references and route; edit or request a revision, then retest |
| Existing writer error | Another process owns the same data directory |
| Session cannot find old content | Browser cookie, hostname/port, or restore from an exported backup |
| Frontend unavailable | Build path passed with `--web-dist`; `npm run build` completed |
| Optional Avatar creation unavailable | Configure an executor and its model dependencies; portable finished assets can be imported |

See [tests](../docs/TESTING.md) for installation checks and [Avatar setup](../docs/AVATARS.md) for optional presentation.
