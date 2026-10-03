# HTTP API

The running backend publishes interactive documentation at `/docs` and its complete request/response schema at `/openapi.json`. [Python SDK](CLIENT.md) handles sessions, polling and recoverable requests.

Start with `POST /api/session`. Retain `rpw_session` and send the returned `csrf_token` as `X-CSRF-Token` on writes. Sessions scope libraries, settings and campaigns. The server validates ownership for reads and writes.

Creation jobs and actions are asynchronous. Poll their returned IDs. Action SSE emits `event: state` with public snapshots. Display committed narrative with its resulting player view. Receipt recovery reuses original request IDs; retries use explicit endpoints. See [contracts](CONTRACTS.md).

| Method | Route | Handler |
| --- | --- | --- |
| `GET` | `/` | `index` |
| `GET` | `/api/actions/{aid}` | `action_status` |
| `POST` | `/api/actions/{aid}/cancel` | `cancel` |
| `GET` | `/api/actions/{aid}/diagnostics` | `action_diagnostics` |
| `GET` | `/api/actions/{aid}/events` | `events` |
| `POST` | `/api/actions/{aid}/retry` | `retry` |
| `GET` | `/api/avatars` | `avatar_library` |
| `POST` | `/api/avatars` | `create_avatar` |
| `GET` | `/api/avatars/capabilities` | `avatar_capabilities` |
| `GET` | `/api/avatars/{aid}` | `avatar_status` |
| `GET` | `/api/avatars/{aid}/files/{filename:path}` | `avatar_asset` |
| `POST` | `/api/avatars/{aid}/{operation}` | `avatar_control` |
| `POST` | `/api/backups/{operation}` | `restore` |
| `GET` | `/api/campaigns` | `campaigns` |
| `POST` | `/api/campaigns` | `new_campaign` |
| `GET` | `/api/campaigns/{cid}/backup` | `backup` |
| `GET` | `/api/campaigns/{cid}/branches` | `branches` |
| `POST` | `/api/campaigns/{cid}/branches` | `fork` |
| `POST` | `/api/campaigns/{cid}/branches/{bid}/actions` | `action` |
| `GET` | `/api/campaigns/{cid}/branches/{bid}/export` | `export` |
| `GET` | `/api/campaigns/{cid}/branches/{bid}/memories` | `memories` |
| `GET` | `/api/campaigns/{cid}/branches/{bid}/view` | `view` |
| `GET` | `/api/catalog` | `starter_catalog` |
| `GET` | `/api/community` | `community` |
| `GET` | `/api/community/{pid}` | `community_package` |
| `GET` | `/api/community/{pid}/download` | `download_package` |
| `POST` | `/api/community/{pid}/install` | `community_install` |
| `POST` | `/api/decisions/{role}` | `decision` |
| `GET` | `/api/engines` | `engines` |
| `POST` | `/api/engines/{role}/check` | `check_engine` |
| `POST` | `/api/rooms` | `create_room` |
| `POST` | `/api/rooms/join` | `join_room` |
| `GET` | `/api/rooms/{rid}` | `room_view` |
| `POST` | `/api/rooms/{rid}/actions` | `room_action` |
| `GET` | `/api/rooms/{rid}/actions/{aid}` | `room_action_view` |
| `POST` | `/api/rooms/{rid}/actions/{aid}/{operation}` | `room_action_control` |
| `GET` | `/api/rooms/{rid}/avatars/{aid}` | `room_avatar_status` |
| `GET` | `/api/rooms/{rid}/avatars/{aid}/files/{filename:path}` | `room_avatar_asset` |
| `POST` | `/api/rooms/{rid}/control` | `room_control` |
| `GET` | `/api/rooms/{rid}/export` | `room_export` |
| `GET` | `/api/rooms/{rid}/memories` | `room_memories` |
| `POST` | `/api/session` | `session` |
| `DELETE` | `/api/settings/provider` | `reset_provider` |
| `GET` | `/api/settings/provider` | `provider` |
| `PUT` | `/api/settings/provider` | `save_provider` |
| `POST` | `/api/settings/provider/check` | `check_provider` |
| `GET` | `/api/settings/usage` | `usage` |
| `GET` | `/api/status` | `status` |
| `GET` | `/api/studio` | `studio_library` |
| `POST` | `/api/studio/catalog/{key}/install` | `install_starter` |
| `GET` | `/api/studio/imports` | `import_library` |
| `POST` | `/api/studio/imports` | `upload_import` |
| `POST` | `/api/studio/imports/{iid}/convert` | `convert_import` |
| `GET` | `/api/studio/imports/{iid}/original` | `original_import` |
| `GET` | `/api/studio/jobs/{jid}` | `creation_status` |
| `POST` | `/api/studio/jobs/{jid}/cancel` | `cancel_creation` |
| `POST` | `/api/studio/jobs/{jid}/retry` | `retry_creation` |
| `GET` | `/api/studio/packages` | `own_packages` |
| `POST` | `/api/studio/packages` | `make_package` |
| `POST` | `/api/studio/packages/import` | `import_package` |
| `POST` | `/api/studio/packages/preview` | `preview_package_upload` |
| `PUT` | `/api/studio/packages/{pid}/visibility` | `package_visibility` |
| `PUT` | `/api/studio/stories/{sid}` | `edit_story` |
| `GET` | `/api/studio/stories/{sid}/export` | `export_story` |
| `POST` | `/api/studio/stories/{sid}/repair` | `repair_story` |
| `POST` | `/api/studio/stories/{sid}/test` | `test_story` |
| `POST` | `/api/studio/worlds` | `create_world` |
| `PUT` | `/api/studio/worlds/{wid}` | `edit_world` |
| `POST` | `/api/studio/worlds/{wid}/archive` | `archive_world` |
| `POST` | `/api/studio/worlds/{wid}/stories` | `create_story` |
| `GET` | `/api/worlds` | `worlds` |
| `GET` | `/healthz` | `health` |
