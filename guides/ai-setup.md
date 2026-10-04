# Set up with Codex or Claude Code

[English](ai-setup.md) · [简体中文](zh-CN/ai-setup.md) · [日本語](ja/ai-setup.md)

Open the repository in your coding assistant and adapt the setup fields of this task:

```text
Set up NarraLoom and verify a working story-game framework.
My preferred interface/content language: [English / Simplified Chinese / Japanese / another content language]
My model choice: [provider API / existing local service / recommend for my hardware]
My environment and workspace directories: [choose paths or recommend new ones]
My goal: [reference frontend / backend API / model comparison]
My operating system / GPU: [Linux / Windows WSL2 / macOS; GPU model and VRAM]
2D presentation: [finished assets / generate from reference images / text only]

Read README.md, guides/quickstart.md, guides/models.md, guides/developers.md
and applicable workspace instructions. Inspect Python, Node, storage and any
existing inference services. On shared hardware, use its established account
and GPU scheduling workflow.

1. Choose a dedicated environment and install the backend. Build the reference
   frontend when requested. Keep caches and runtime files in the workspace.
2. Configure the provider endpoint, exact model ID, JSON mode and private key
   source. Reuse compatible existing services. Explain the model role mapping.
3. Start one backend writer. Check /healthz, /docs and the selected model module.
4. Run python scripts/verify.py --distribution. Use a separate workspace for
   destructive or restart checks.
5. With the configured real model, create a small world and story, inspect its
   automatic test report, start a campaign, submit one action and recover it
   after refreshing. Exercise SDK persistence when the goal is backend use.
6. Report the URL, configuration locations, verification results and exact
   start/stop instructions. Keep credentials and generated private content out
   of commits and public reports.

If I bring a research model, use guides/research.md to change one module and
record its actual response model, failures, latency and usage.
Read guides/avatars.md before enabling image-based creation. Select the OS route in
guides/quickstart.md, inspect capacity, use narraloom models download --dry-run
then the selected endpoint or --mirror. Install isolated creator environments only
when needed, preserve existing configs and the host scheduler, run models check,
and verify one actual creation before reporting the creator ready.

```

Optional 2D creation has its own executor and model dependencies. Configure it when selected; see [Avatar](reference/avatars.md).

[Optional 2D characters: model requirements, Linux/WSL2 environments and mirror downloads](avatars.md)
