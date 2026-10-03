# Sources and licenses

Original NarraLoom code is [MIT](LICENSE). The following sources retain their upstream terms.

| Component | Source / version | Terms |
| --- | --- | --- |
| SSE framing helper | Roleplay Avatar `4e69b83` | [MIT notice](licenses/roleplay-avatar-MIT.txt) |
| Optional Avatar worker and WebGL portrait stage | Roleplay Avatar `32d3fa444b11a4a01bdda28befef8050581f31ab` | [MIT](vendor/avatar_worker/LICENSE), [source hashes](vendor/avatar_worker/UPSTREAM.json) |
| Lantern Barrow and Emberback text/data | Covel `1d2571cdba9dc897eb4ad024819328151d124ab6` | [MIT, Covel Contributors](resources/community/covel/LICENSE) |
| Apartment Test Director text/data | World-Forge `612d117af08bd50f9f5bb09f4cfe327a7ff5a3a9` | [MIT, Danut Niculae](resources/community/world-forge/LICENSE) |
| React, Vite | npm lockfile | MIT |
| TypeScript | npm lockfile | Apache-2.0 |
| Lucide | npm lockfile | ISC |

[Starter notes](docs/COMMUNITY_CONTENT.md) describe the playable adaptations. The apartment dinner storyline and Fogharbor are original NarraLoom content. Original resource notices are included in portable starter exports.

The optional Jev runtime is downloaded separately at the pinned [source revision](resources/jev-style-source-pin.json). Model weights and inference services retain their own source/model-card terms. Optional Avatar model/resource dependencies follow [Roleplay Avatar's resource documentation](https://github.com/Toyhom/RoleplayAvatar).

The [Avatar adapter](vendor/avatar_worker/ADAPTER.md) documents the host interface. Upstream source hashes identify inputs; NarraLoom-specific adaptations support scoped assets, stable creation requests and renderer lifecycle management.
