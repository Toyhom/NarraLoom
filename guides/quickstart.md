# Quick start

[English](quickstart.md) · [简体中文](zh-CN/quickstart.md) · [日本語](ja/quickstart.md)

An API-backed setup runs the framework on a CPU machine. A local-model setup connects the same backend to your inference server. Start with one capable instruction model for every generation role; split roles after your first working story.

## Install

Use Python 3.11+ and, for the reference frontend, Node.js 20+:

```bash
git clone https://github.com/Toyhom/NarraLoom.git
cd NarraLoom
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
npm ci
npm run build
narraloom serve --workspace . --web-dist web/dist
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell. Open **http://localhost:18090**. The language selector offers English, Simplified Chinese and Japanese.

## Connect a model

Open **Models & usage**, enter an OpenAI-compatible base URL, the provider's exact model ID and your key. Local unauthenticated endpoints may leave the key empty. Select the supported JSON mode, save, then test the connection. [Models](models.md) explains per-module bindings and provider examples.

The browser's settings belong to its session. For a server-wide default, copy `configs/models.example.json` to `configs/models.local.json`, edit its endpoint/model, and set the environment variable named by `api_key_env` before starting the backend. Restart to reload file settings. Keep the base URL's `/v1` when your provider requires it.

## Create and play

1. Choose **Create my world**. Select a single scene, short story or exploration adventure, and set the content language.
2. Describe the setting and optionally the first story. Generation creates editable places, characters and an outline, then checks and playtests the story.
3. When its current revision passes, name your player and start. If a report fails, inspect the explanation, edit or request an AI revision, and test again.
4. Talk, investigate, move or wait. The engine records consequences. Return to the world to create another story.

The built-in Fogharbor adventure is available from the home page. Community starters become editable copies and run their own tests. Generation and playtests use your model provider and its billing.

## Backend only

```bash
python -m pip install .
narraloom serve --workspace /path/to/my-game --models-config /path/to/models.local.json
```

Open **http://localhost:18090/docs** for the API, or run `python examples/headless.py --world 'A quiet reading room' --preset scene --language en` from the checkout. The example saves its session and pending requests; `--resume` continues them. See the [developer guide](developers.md).

For a failed connection, check the endpoint, model ID, authentication and JSON mode. For a failed story test, open the job report; a successful connection only confirms the model protocol. [Deployment](deployment.md) covers recovery and backups.

[Reference workspace](workspace.md)
