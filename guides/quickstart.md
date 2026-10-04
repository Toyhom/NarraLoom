# Quick start

[English](quickstart.md) · [简体中文](zh-CN/quickstart.md) · [日本語](ja/quickstart.md)

Start with text characters: world creation, dialogue and gameplay use your configured text model. Animated 2D portraits are an optional enhancement, disabled by default in the creation form. You can enable them now or add them later. See [optional portrait setup](avatars.md) when you want to import or generate a portrait.

## Choose your platform

| Computer | Run the backend | Create new 2D portraits |
| --- | --- | --- |
| Linux | Python installation below, or a Linux container | NVIDIA CUDA, x86-64 host and the [creator setup](avatars.md) |
| Windows | WSL2 Ubuntu, or Docker Desktop with Linux containers | WSL2 with an NVIDIA GPU; run creator commands inside WSL |
| macOS, Intel or Apple Silicon | Docker Desktop Linux container, or a remote Linux host | Use a Linux NVIDIA host; finished assets display in the Mac browser |

The current backend uses Linux writer locks. On Windows, install WSL with `wsl --install -d Ubuntu-24.04`, restart if requested, then run the Linux instructions in the Ubuntu terminal. A browser can run on any of these systems.

## Linux / WSL2 installation

Use Python 3.11+ and Node.js 20+. From a Linux shell:

```bash
git clone https://github.com/Toyhom/NarraLoom.git
cd NarraLoom
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
npm ci
npm run build
narraloom serve --workspace . --web-dist web/dist
```

Open **http://localhost:18090**. Select English, Simplified Chinese or Japanese. Stop the foreground service with **Ctrl+C**; run the same `narraloom serve` command to start it again. Contributors can install `.[dev]` for tests.

## macOS / Docker Desktop

Install Git and Docker Desktop, start Docker, then run these commands in Terminal. The same commands work in Windows PowerShell with Linux containers:

```bash
git clone https://github.com/Toyhom/NarraLoom.git
cd NarraLoom
docker build -t narraloom .
docker run -d --name narraloom --hostname narraloom -p 127.0.0.1:18090:18090 -v narraloom-workspace:/workspace narraloom
```

Open **http://localhost:18090** and configure your API through the UI. The image includes the backend, built frontend and finished-portrait support. It uses a persistent named volume for saves and settings. Keep one container per volume and retain its hostname when recreating it. Use `docker stop narraloom`, `docker start narraloom` and `docker logs --tail 80 narraloom` to manage it. Initial image building downloads Python/Node packages. GPU creation is configured separately on its Linux/WSL2 host.

To reach a model service on the Docker Desktop host, use `http://host.docker.internal:<port>/v1`. Inside a container, `127.0.0.1` refers to the container. On Linux Docker, add `--add-host host.docker.internal:host-gateway` to `docker run` and make the model service reachable from that interface.

## Use a remote Linux host

Install and start on the server, then run this on your Windows, Mac or Linux computer:

```bash
ssh -N -L 18090:127.0.0.1:18090 user@your-server
```

Open **http://localhost:18090**. Keep the tunnel running; Ctrl+C closes the tunnel while the server continues to run.

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
