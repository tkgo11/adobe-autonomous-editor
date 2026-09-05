# Install / Apply the Adobe Autonomous Editor Skill

This repository is already laid out as a complete **Agent Skill directory**. Do **not** copy only `SKILL.md`: the root skill intentionally references `runtime/`, `scripts/`, `workflows/`, `templates/`, `schemas/`, `references/`, and the internal initializer under `skills/`.

The easiest installation is therefore to clone the **whole repository** directly into a standard Agent Skills directory.

## Recommended: Codex on Windows (user-wide)

Install once for all projects:

```powershell
$installer = Join-Path $env:TEMP "install-adobe-autonomous-editor.ps1"
Invoke-WebRequest "https://raw.githubusercontent.com/tkgo11/adobe-autonomous-editor/main/install.ps1" -OutFile $installer
& $installer
```

This installs or updates the skill at:

```text
%USERPROFILE%\.agents\skills\adobe-autonomous-editor\
```

Then fully restart Codex, or start a new session, and invoke:

```text
$adobe-autonomous-editor
```

Example:

```text
$adobe-autonomous-editor Use D:\Footage\shoot as the source. Create a polished 60-second 9:16 product video with fast pacing, clean captions, motion graphics, sound design, color grading, and final H.264 delivery. Handle Premiere Pro and After Effects autonomously and only stop for a real external permission/license blocker.
```

You do **not** need to manually run the internal initialize skill. The root skill requires `skills/initialize/SKILL.md` to run before editing.

## Fastest manual install (Git only)

If you prefer not to run a downloaded installer:

```powershell
git clone https://github.com/tkgo11/adobe-autonomous-editor.git "$env:USERPROFILE\.agents\skills\adobe-autonomous-editor"
```

Update later with:

```powershell
git -C "$env:USERPROFILE\.agents\skills\adobe-autonomous-editor" pull --ff-only
```

## Project-only installation

Use this when the skill should only be visible in one project/repository.

From the project root:

```powershell
$installer = Join-Path $env:TEMP "install-adobe-autonomous-editor.ps1"
Invoke-WebRequest "https://raw.githubusercontent.com/tkgo11/adobe-autonomous-editor/main/install.ps1" -OutFile $installer
& $installer -Scope Project -ProjectRoot (Get-Location).Path
```

This produces:

```text
<project>/
└── .agents/
    └── skills/
        └── adobe-autonomous-editor/
            ├── SKILL.md
            ├── agents/
            │   └── openai.yaml
            ├── skills/
            ├── workflows/
            ├── runtime/
            ├── scripts/
            ├── templates/
            ├── schemas/
            └── references/
```

Equivalent Git command:

```powershell
git clone https://github.com/tkgo11/adobe-autonomous-editor.git ".agents\skills\adobe-autonomous-editor"
```

## Why `.agents/skills`?

The Agent Skills format discovers a skill from a directory containing `SKILL.md`, and current Codex/Agent Skills conventions use `.agents/skills/<skill-name>/SKILL.md` for project skills and `~/.agents/skills/<skill-name>/SKILL.md` for user skills.

This repository keeps `SKILL.md` at its root specifically so that a direct clone into `.../.agents/skills/adobe-autonomous-editor` is immediately discoverable without copying or rearranging files.

## Codex UI metadata

The repository includes:

```text
agents/openai.yaml
```

with the Codex-facing display name, short description, and a default `$adobe-autonomous-editor` prompt. This is optional in the open Agent Skills specification but recommended by OpenAI for Codex skill UI/discovery.

## Verify the installation

User-wide Windows installation:

```powershell
$skill = "$env:USERPROFILE\.agents\skills\adobe-autonomous-editor"
Test-Path "$skill\SKILL.md"
Test-Path "$skill\agents\openai.yaml"
python "$skill\tests\selftest.py"
```

A valid package self-test ends with:

```text
SELFTEST_OK
```

If Python is not installed yet, the installer can still place the skill correctly; the autonomous initializer will report missing runtime prerequisites when an edit job actually starts.

## Updating

Re-run `install.ps1`. If the destination is already a Git checkout, it performs a fast-forward update instead of creating another copy.

Or update manually:

```powershell
git -C "$env:USERPROFILE\.agents\skills\adobe-autonomous-editor" pull --ff-only
```

## Uninstalling

User-wide install:

```powershell
Remove-Item "$env:USERPROFILE\.agents\skills\adobe-autonomous-editor" -Recurse -Force
```

Project install:

```powershell
Remove-Item ".agents\skills\adobe-autonomous-editor" -Recurse -Force
```

Restart the agent afterwards so its skill catalog refreshes.

## macOS / Linux skill installation

The open Agent Skill itself can be installed into the same user/project directory convention:

```bash
curl -fsSL https://raw.githubusercontent.com/tkgo11/adobe-autonomous-editor/main/install.sh -o /tmp/install-adobe-autonomous-editor.sh
bash /tmp/install-adobe-autonomous-editor.sh
```

Project scope:

```bash
bash /tmp/install-adobe-autonomous-editor.sh --project "$PWD"
```

The current **desktop execution runtime is Windows-first**, because its deepest fallback uses Windows UI Automation and the bundled bootstrap scripts target Windows Adobe installations. Installing the skill on another OS does not imply feature parity with the Windows runtime.

## ChatGPT skill upload

Where ChatGPT Skills upload is available, the Agent Skills format can also be uploaded as a folder/ZIP through the Skills UI. However, this package's full Premiere Pro / After Effects automation requires a local agent environment that can access local files, launch Adobe applications, execute the bundled scripts, and perform desktop control. Installing the instructions alone in a cloud-only environment does not grant access to your local Adobe desktop.

## Troubleshooting discovery

If the skill is installed but not shown:

1. Confirm the exact path ends in `adobe-autonomous-editor/SKILL.md` and that there is **not** an accidental extra nesting such as `adobe-autonomous-editor/adobe-autonomous-editor/SKILL.md`.
2. Confirm `SKILL.md` starts with `name: adobe-autonomous-editor` in YAML frontmatter.
3. Restart Codex completely or open a fresh session so the skill catalog is rebuilt.
4. Try explicit invocation with `$adobe-autonomous-editor`.
5. Run `tests/selftest.py` to detect package corruption.

## Repository layout contract

Keep these paths together when distributing the skill:

```text
adobe-autonomous-editor/
├── SKILL.md                 # Agent Skill entry point (required)
├── agents/openai.yaml       # Codex UI metadata
├── skills/initialize/       # Mandatory internal initialization skill
├── workflows/               # Lazy-loaded editing workflow modules
├── runtime/                 # Executable local control plane
├── scripts/                 # Bootstrap / QC / helper entry points
├── templates/               # Premiere UXP bridge and AE templates
├── schemas/                 # Machine-readable plan/job schemas
├── references/              # Detailed architecture/control guidance
└── tests/selftest.py        # Package integration validation
```

The top-level `SKILL.md` uses relative paths from this directory, which is why the whole directory is the installable unit.
