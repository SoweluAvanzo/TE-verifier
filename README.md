# Token Economy Verifier

A pre-deployment checker for community token economies. You describe a
token economy, either by filling in a questionnaire in the browser or by
writing a YAML spec. The tool then checks it against the **six failure
modes** in the DLT2026 paper *"Six Failure Modes: A Pre-Deployment
Diagnostic Framework for Tokenized Collaborative Economies"*:

| # | Failure mode | Violation condition |
|---|---|---|
| FM1 | Token oversupply / inflation spiral | `E(t) > P·Q/V` |
| FM2 | Velocity trap | `τ̄ → 1` |
| FM3 | Burn/emission imbalance | `E(t) − B(t) > g(t)·M(t)` |
| FM4 | Free-rider / contribution collapse | `φ < d/K` or `γS ≤ T − R` |
| FM5 | Insufficient critical mass | `N < 2Kd + 1` |
| FM6 | Governance capture | `Γ > 0.5` |

Verification runs in two stages:

1. **Static / formal check** (Z3 SMT solver). Each failure mode gets a
   verdict, plus a concrete counterexample when it fails.
2. **Dynamic check** (agent-based simulation). It produces trajectories,
   Monte Carlo violation probabilities and network views. It is used when
   the static check is inconclusive, or when you want to see concrete
   numbers over time.

---

## Contents

- [Option A: run with Docker (recommended)](#option-a-run-with-docker-recommended)
- [Option B: run natively with Python (macOS / Linux / Windows)](#option-b-run-natively-with-python)
- [Using the app in the browser](#using-the-app-in-the-browser)
- [Command-line tools](#command-line-tools)
- [Running the tests](#running-the-tests)
- [Troubleshooting](#troubleshooting)
- [Repository layout and further docs](#repository-layout-and-further-docs)

---

## Option A: run with Docker (recommended)

Docker is the easiest option. It doesn't depend on which Python version
you have installed, and it works the same way on macOS (Intel and Apple
Silicon), Linux and Windows.

### 1. Install the prerequisites

| Platform | What to install |
|---|---|
| **macOS** | [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/): pick the *Apple Silicon* or *Intel* build to match your Mac (Apple menu → *About This Mac*). Alternatively, with Homebrew: `brew install --cask docker`. Then open Docker Desktop once and wait until it says *Engine running*. |
| **Windows** | [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/) (with the WSL 2 backend). |
| **Linux** | [Docker Engine](https://docs.docker.com/engine/install/). Optionally add yourself to the `docker` group so you don't need `sudo`. |
| **All** | [Git](https://git-scm.com/downloads), to clone the repository. On macOS, `git` comes with the Xcode Command Line Tools: `xcode-select --install`. |

Check that Docker is running:

```bash
docker --version
docker info > /dev/null && echo "Docker is running"
```

### 2. Get the code

```bash
git clone https://github.com/SoweluAvanzo/TE-verifier.git
cd TE-verifier
```

### 3. Build the image

```bash
docker build -t token-economy-verifier .
```

The first build takes a couple of minutes because it downloads Python and
the Z3 solver. Later builds use the cache.

### 4. Run the app

```bash
docker run --rm -p 8000:8000 --name te-verifier token-economy-verifier
```

Open **<http://localhost:8000>** in your browser. To stop the app, press
`Ctrl+C` in the terminal, or run `docker stop te-verifier` from another
terminal.

To run it in the background instead:

```bash
docker run -d --rm -p 8000:8000 --name te-verifier token-economy-verifier
docker logs -f te-verifier     # follow the logs (Ctrl+C stops following, not the app)
docker stop te-verifier        # stop it
```

If port 8000 is already in use on your machine, map a different host port,
for example `-p 8080:8000`, and open <http://localhost:8080>.

### Alternative: Docker Compose

The repository also includes a hardened Compose file that publishes the
app on port **8888**:

```bash
docker compose -f infra/compose.yml up -d --build
# open http://localhost:8888
docker compose -f infra/compose.yml down
```

> **Note:** `infra/compose.yml` binds to all network interfaces, so other
> machines on your network can reach the app. For purely local use, prefer
> the `docker run` command above, or change the port mapping to
> `"127.0.0.1:8888:8000"`.

### Rebuilding after you change the code

The image contains a copy of the code. After editing files, rebuild and
restart:

```bash
docker build -t token-economy-verifier .
docker run --rm -p 8000:8000 --name te-verifier token-economy-verifier
```

---

## Option B: run natively with Python

Use this option if you want to develop the code, run the test suite, or
use the command-line tools directly.

### 1. Install the prerequisites

The project needs **Python 3.11 or newer** (3.12 is recommended) and Git.
Every Python dependency installs as a prebuilt wheel, including the Z3
solver for both Intel and Apple Silicon Macs, so **you don't need a C
compiler**.

**macOS.** The `python3` that ships with macOS is too old (3.9), so
install a newer one with [Homebrew](https://brew.sh):

```bash
# Install Homebrew if you don't have it (see https://brew.sh)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.12 git
python3.12 --version            # should print Python 3.12.x
```

You can also use the official installer from
<https://www.python.org/downloads/macos/>.

**Linux (Debian / Ubuntu):**

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
python3 --version               # must be 3.11 or newer
```

**Windows:** install Python 3.12 from <https://www.python.org/downloads/windows/>
and tick *"Add python.exe to PATH"*. Then use the PowerShell variants below.

### 2. Get the code

```bash
git clone https://github.com/SoweluAvanzo/TE-verifier.git
cd TE-verifier
```

### 3. Create a virtual environment and install the dependencies

macOS / Linux:

```bash
python3.12 -m venv .venv        # on Linux, `python3 -m venv .venv` is fine if python3 ≥ 3.11
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[webapp,dev]"
```

Windows (PowerShell):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[webapp,dev]"
```

This installs:

| Package | Purpose |
|---|---|
| `z3-solver` | SMT solver behind the static checks |
| `pydantic`, `pyyaml` | Spec (TE-IR) schema and YAML parsing |
| `numpy`, `networkx` | Simulation and network analytics |
| `flask` *(extra `webapp`)* | Web user interface |
| `pytest` *(extra `dev`)* | Test suite |

It also adds two command-line tools to your environment: `te-verify` and
`te-simulate`.

### 4. Start the web app

From the repository root, with the virtual environment activated:

```bash
flask --app webapp.app run --port 5001
```

Open **<http://127.0.0.1:5001>** in your browser. Press `Ctrl+C` to stop.

> **Why port 5001?** On macOS 12 and later, port 5000 is taken by the
> *AirPlay Receiver*, so a server on 5000 either fails to start or returns
> `403 Forbidden`. Any free port works. The shortcut
> `python -m webapp.app` always uses port 5000. It is fine on Linux, and
> works on macOS if you turn off *System Settings → General → AirDrop &
> Handoff → AirPlay Receiver*.

To reload automatically while you edit the code, add `--debug`:
`flask --app webapp.app run --port 5001 --debug`.

When you come back later, you only need to reactivate the environment:

```bash
cd TE-verifier
source .venv/bin/activate       # Windows: .venv\Scripts\Activate.ps1
flask --app webapp.app run --port 5001
```

---

## Using the app in the browser

> The UI loads two charting libraries (Chart.js and Cytoscape.js) from a
> CDN, so the browser needs internet access for the charts and graphs to
> appear. The verifier itself runs entirely on your machine or container.

The app has three pages. A step navigator on the left links the two main
steps: **1. Verify**, then **2. Explore trajectory**.

### `/`: Questionnaire (the main entry point)

A guided form that follows the paper's parameter groups. Each question
has a **"Why we ask"** explainer showing which failure mode it feeds
and why.

1. **Start from an example (optional).** Click one of the example buttons
   at the top, such as `bitcoin`, `ethereum`, `makerdao`, `curve_vecrv`,
   `axie_infinity`, `time_bank` or `cascina_roccafranca`. The button
   fills in the whole form and verifies it straight away, so you can see
   a worked report.
2. **Describe your token economy**, section by section:
   - **System**: name, description, archetype.
   - **Tokens (Group 1)**: function, earning mechanisms, value anchor,
     holding incentives, contribution verification, redemption, offer
     variety `K`. Use **+ Add token** for multi-token systems.
   - **Mint mechanisms (Group 2) and burn mechanisms (Group 3)**: one or
     more per token. Each mechanism has a function class and a rate range,
     or a **DSL expression** (for example
     `event.amount * event.duration / param.max_lock`, see
     [docs/dsl-reference.md](docs/dsl-reference.md)). Mechanisms can be
     linked to events, gated by conditions, given regime switches
     (piecewise behaviour), and given advanced options such as cap,
     halving and vesting.
   - **Cross-token flows**: one token's event mints or burns another token
     (proportional or independent coupling).
   - **Events** and **non-tokenized assets**: what triggers emissions,
     and goods or services that tokens pay for.
   - **Declared flow graph**: a live diagram of the mint, burn and transfer
     flows you have declared. Use **↻ Refresh preview** to update it.
   - **Governance (Group 4)**: governance type, who controls each decision,
     monitoring `γ`, sanctions `S`, vote weighting.
   - **Participants (Group 5)**: `N`, volume `Q`, demand `d`, growth,
     topology, agent types and population events.
   - **Non-functional requirements (NFR1–NFR7)**: how important resilience,
     accessibility, circulation speed and so on are to you. These change
     whether a failure mode counts as a risk or as intended behaviour.
3. **Click ▶ Verify.** The **Verdict** pane on the right shows, for each
   failure mode:
   - the status (PASS / FAIL / INCONCLUSIVE / PASS AS INTENDED);
   - the formal condition and the values that make it fail;
   - a concrete **counterexample** scenario;
   - **recommendations**, such as the critical value to aim for and which
     design choices would satisfy it;
   - a risk band (GREEN / AMBER / RED);
   - any **coherence issues**, which are internal contradictions in the
     spec.

   Change any field and click **Verify** again. The verdict pane stays
   visible, so you can iterate quickly.
4. **Save and reload.** **⬇ Download YAML** saves your design as a spec
   file. **Upload YAML…** loads it back. **Reset form** clears everything.
5. **Click ▶ Explore trajectory** to send the current design to the
   simulation page.

### `/explore`: Trajectory Explorer (simulation)

This page runs one seeded agent-based simulation and shows it period by
period.

1. Load an example, or paste or keep a YAML spec in the **YAML spec** box.
2. Set the **Run config**: *Horizon* (number of periods), *Seed* (the same
   seed gives the same run) and *Max agents* (fewer is faster).
3. Click **Run trajectory**. You then get:
   - **Results synthesis**: final supply, cumulative emission and burn,
     concentration drift, participation, and per-role final state.
   - **Time-series charts**: balance per role, balance share, Gini and φ,
     action mix, live population, reputation, event occurrences,
     non-tokenized asset flows.
   - **Failure-mode coherence**: whether the simulation agrees with the
     static verdicts.
   - **Declared flow graph** and **trade network**. Use the **Period**
     slider or **▶ Play** to watch the network evolve. You can color nodes
     by role or balance and see the balance histogram for any period.

### `/yaml`: Advanced YAML editor

This page is for full control over the spec (TE-IR): rare asymptotic
families, complex regime switches and so on. Paste or edit YAML, then
click **Verify** to get the same verification report. The six failure
modes are explained at the top of the page. The YAML files in
[`examples/`](examples/) are good starting points.

### JSON API

The pages are built on a JSON API, which you can also call directly
(change the port to match how you started the app):

```bash
curl -s http://localhost:8000/api/example/bitcoin           # example spec as YAML text
curl -s -X POST http://localhost:8000/api/verify \
     -H 'Content-Type: application/json' \
     -d "{\"yaml\": $(python3 -c 'import json,sys;print(json.dumps(open("examples/bitcoin.yaml").read()))')}"
```

| Route | Method | Purpose |
|---|---|---|
| `/api/verify` | POST | `{yaml}` → verification report JSON |
| `/api/build-and-verify` | POST | `{ir}` (form JSON) → report + serialized YAML |
| `/api/minimal-verdicts` | POST | `{yaml}` → minimal reachability verdicts |
| `/api/simulate` | POST | `{yaml, n_runs, horizon_periods, seed}` → Monte Carlo ABM report |
| `/api/explore` | POST | `{yaml, horizon_periods, seed, max_agents}` → per-period trajectory |
| `/api/flow-graph` | POST | `{yaml}` → declared flow graph |
| `/api/cadcad-export` | POST | `{yaml, ...}` → cadCAD-compatible config |
| `/api/conditions` | GET | Explanations of the six failure modes |

The report format is documented in [docs/api-contract.md](docs/api-contract.md).
The server allows 30 POST requests per minute per IP address.

---

## Command-line tools

These require the native install (Option B), with the virtual environment
activated. You can also run them inside the Docker image, for example
`docker run --rm token-economy-verifier te-verify examples/bitcoin.yaml`.

```bash
# Static verification: human-readable report
te-verify examples/axie_infinity.yaml

# Same, as JSON
te-verify examples/axie_infinity.yaml --json

# Minimal reachability verdicts (sound / fragile / broken per FM)
te-verify examples/axie_infinity.yaml --minimal

# Override paper-default thresholds and calibrations
te-verify examples/axie_infinity.yaml --config overrides.yaml

# Monte Carlo agent-based simulation: P(violation) and time-to-violation per FM
te-simulate examples/bitcoin.yaml --runs 200 --horizon 260 --seed 1
te-simulate examples/bitcoin.yaml --simulate-all --json
```

Run `te-verify --help` or `te-simulate --help` for every option.

---

## Running the tests

```bash
source .venv/bin/activate
pytest                      # the full suite takes about 5 minutes (simulation-heavy)
pytest tests/test_model_checker_oracles.py -v   # a quick, focused subset
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ERROR: Package 'token-economy-verifier' requires a different Python` | Your Python is older than 3.11. On macOS, use `python3.12 -m venv .venv` after `brew install python@3.12`. |
| `Address already in use`, or `403 Forbidden` on port 5000 (macOS) | AirPlay Receiver is using port 5000. Use `flask --app webapp.app run --port 5001`. |
| `flask: command not found` / `te-verify: command not found` | The virtual environment isn't active. Run `source .venv/bin/activate`. |
| `zsh: no matches found: .[webapp,dev]` | Quote the argument: `pip install -e ".[webapp,dev]"`. |
| `Cannot connect to the Docker daemon` | Start Docker Desktop and wait for *Engine running*. |
| `Bind for 0.0.0.0:8000 failed: port is already allocated` | Use another host port: `docker run --rm -p 8080:8000 token-economy-verifier`. |
| Charts or graphs are empty | The browser can't reach `cdn.jsdelivr.net`. Check your internet or proxy settings. |
| Verification of a large spec times out in Docker | The container's server stops requests that take longer than 60 s. Run natively (Option B) or with the CLI, which have no time limit. |

---

## Repository layout and further docs

```
schema/        Pydantic models for the token-economy spec (TE-IR) + expression DSL
verifier/      Static verifier (Z3), failure-mode checkers, ABM simulator (verifier/abm)
webapp/        Flask app: templates/ and static/ for the browser UI
examples/      Case-study specs (Bitcoin, Ethereum, MakerDAO, Curve, Axie, …)
tests/         pytest suite
docs/          Architecture, proofs, API contract, DSL reference, …
Dockerfile     Production image (gunicorn on port 8000)
infra/         Docker Compose file
```

Useful docs:

- [webapp/README.md](webapp/README.md): web app internals
- [docs/tier1-assessment.md](docs/tier1-assessment.md): what is built and the empirical results
- [docs/case-studies.md](docs/case-studies.md): the case-study failure-mode traces
- [docs/dsl-reference.md](docs/dsl-reference.md): the expression DSL for mint and burn functions
- [docs/api-contract.md](docs/api-contract.md): report JSON format
- [docs/proofs/](docs/proofs/): formal derivations for every failure mode
