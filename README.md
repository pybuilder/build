# PyBuilder GitHub Action

This is a one-shot Python build GitHub action for PyBuilder. It drives PyBuilder's own multi-OS build system and serves
as a shortcut for the following build chain steps:

1. Checkout code
2. Setup Python Environment (optionally via Homebrew)
3. Create a VirtualEnv
4. Install PyBuilder
5. Run the build

Each step can be skipped or omitted or parameterized.

## Usage

### Basic

The most basic usage is as follows:

```yaml
steps:
  - uses: pybuilder/build@master
```

This will:

1. Checkout the project
2. Install default Python without Homebrew
3. Install latest PyBuilder compatible with installed Python.
4. Run the build with default PyBuilder parameters.

### Advanced

Somewhat more interesting scenario that exploits parameter overrides:

```yaml
jobs:
  build:
    runs-on: ${{ matrix.os }}
    continue-on-error: false
    strategy:
      fail-fast: false
      matrix:
        os:
          - ubuntu-latest
        python-version:
          - '3.14'
          - '3.13'
          - '3.12'
    permissions:
      contents: write
    env:
      DEPLOY_PYTHONS: "3.14"
      DEPLOY_OSES: "Linux"
      TWINE_USERNAME: __token__
      TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}
      GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    steps:
      - uses: pybuilder/build@master
        with:
          python-version: ${{ matrix.python-version }}
          is-upload: >-
            ${{ github.event_name == 'push'
            && contains(env.DEPLOY_OSES, runner.os)
            && contains(env.DEPLOY_PYTHONS, matrix.python-version) }}
```

The above example overrides Python versions using matrix strategy and uses the `is-upload` input to conditionally
trigger the `upload` task when the OS and Python version match the deploy configuration. Release automation is
enabled by default, so adding `[release]` to a merge commit message will automatically tag, create a GitHub Release,
and bump to the next dev version.

## Reference

### Checkout

Checkout via `actions/checkout@v5` if enabled.

```yaml
  checkout:
    description: 'Do checkout first'
    default: 'true'
```

### Install Python

Python is installed via `actions/setup-python@v6`, unless Homebrew is requested.

```yaml
  install-python:
    description: 'Whether to install Python'
    default: 'true'
```

#### Whether to Install Python with Homebrew

Install Python via Homebrew instead. This only has effect on MacOS.

```yaml
  homebrew-python:
    description: 'Whether Python should be installed via Homebrew'
    default: 'false'
```

#### Python Version to Install

Python version is expected as at least `major.minor`. If using `actions/setup-python@v6` wildcards can be used
after `major`. If installing with Homebrew, only `major.minor` with no wildcards is supported.

```yaml
  python-version:
    description: 'Python version to use, if installing'
    default: '3.11'
```

#### Python Architecture to Install

This is passed to `actions/setup-python@v6` verbatim and has no effect with Homebrew.

```yaml
  architecture:
    description: "Install Python for specific architecture, if installing"
    default: x64
```

### Install Virtualenv

When `true`, the build will be performed in a freshly installed virtualenv. If not, the Python environment (installed or
available) will be used directly.

```yaml
  with-venv:
    description: 'Whether to use Virtualenv during a build'
    default: 'true'
```

### Install PyBuilder

Not installing PyBuilder is only useful if you're developing PyBuilder.

```yaml
  install-pyb:
    description: 'Install PyBuilder'
    default: 'true'
```

#### Specify Version Selector of PyBuilder to Install

A version requirement expression that is passed to `pip` to install PyBuilder.

```yaml
  pyb-version:
    description: 'PyBuilder version to install'
    default: '>=0.12.0'
```

### PyBuilder Command to Run

This is only useful to overwrite if you're developing PyBuilder.

```yaml
  pyb-command:
    description: 'Command to run PyBuilder'
    default: 'pyb'
```

### PyBuilder Command Line Arguments

Default command line arguments.

```yaml
  pyb-args:
    description: 'PyBuilder command line arguments'
    default: "-E ci -v -X"
```

### Extra PyBuilder Command Line Arguments

```yaml
  pyb-extra-args:
    description: 'PyBuilder extra command line arguments'
    default: ""
```

### Run a bash script before PyBuilder build

```yaml
  pre-build:
    description: 'Run a script before PyBuilder build'
    required: false
    default: ""
```

## Upload

The `is-upload` input controls whether the matrix slot runs PyBuilder's `upload` task. When set to `'true'`,
the action appends `+upload` to the PyBuilder arguments internally.

```yaml
  is-upload:
    description: 'Whether this matrix slot runs the PyBuilder upload task'
    default: 'false'
```

This replaces the legacy pattern of using a shell step to conditionally set `PYB_EXTRA_ARGS=+upload`.

**Before** (legacy pattern):
```yaml
    steps:
      - shell: bash
        if: |
          github.event_name == 'push' &&
          contains(env.DEPLOY_OSES, runner.os) &&
          contains(env.DEPLOY_PYTHONS, matrix.python-version)
        run: |
          echo "PYB_EXTRA_ARGS=+upload" >> $GITHUB_ENV
      - uses: pybuilder/build@master
        with:
          python-version: ${{ matrix.python-version }}
          pyb-extra-args: ${{ env.PYB_EXTRA_ARGS }}
```

**After**:
```yaml
    steps:
      - uses: pybuilder/build@master
        with:
          python-version: ${{ matrix.python-version }}
          is-upload: >-
            ${{ github.event_name == 'push'
            && contains(env.DEPLOY_OSES, runner.os)
            && contains(env.DEPLOY_PYTHONS, matrix.python-version) }}
```

Existing workflows that pass `+upload` via `pyb-extra-args` continue to work. However, when using release
automation (`[release]` in commit messages), `is-upload` must be used instead of `pyb-extra-args` for the
upload task.

**Migration for the accumulator pattern**: if your workflow sets `PYB_EXTRA_ARGS=+upload --no-venvs`, split
it into `is-upload: 'true'` for the upload part and `pyb-extra-args: '--no-venvs'` for the remaining flags.

## Release Automation

The action includes built-in release automation triggered by `[release]` or `[release X.Y.Z]` in the merge
commit message on push to the default branch.

### Overview

PyBuilder projects typically keep `version = "X.Y.Z.dev"` in `build.py` on master. When a merge commit
message contains `[release]`, the action automatically:

1. **Strips `.dev`** from the version in `build.py` (working copy modification before build)
2. **Builds** with the release version
3. **Uploads** to PyPI (if `is-upload: 'true'`)
4. **Commits** the release version change and **tags** it (atomic push as distributed lock)
5. **Creates a GitHub Release** with auto-generated notes
6. **Bumps** to the next `.dev` version and pushes

The release automation is enabled by default (`auto-release: 'true'`), which is safe because the release
logic only activates when `[release]` is present in the commit message.

### How It Works

**All matrix jobs** (when `auto-release-version` is `'true'`):
- Detect `[release]` in the commit message
- Strip `.dev` from the version in the working copy (or set the explicit version from `[release X.Y.Z]`)
- Build with the release version

**Upload jobs only** (`is-upload: 'true'`):
- After a successful build and upload, commit the release version change
- Create a lightweight tag (e.g., `v1.0.0`)
- Atomically push the commit and tag to the remote
- If the push succeeds (this job is the "coordinator"), create a GitHub Release and bump to the next `.dev`
- If the push fails (tag already exists), another upload job won the race; skip remaining release steps

### Multi-Architecture Builds

When multiple matrix slots have `is-upload: 'true'` (e.g., different architectures uploading platform-specific
wheels), the atomic `git push` acts as a distributed lock. The first upload job to successfully push the tag
becomes the coordinator and handles the GitHub Release and dev version bump. Other upload jobs detect the tag
already exists and skip these steps. The `--atomic` flag ensures either all refs (tag + branch) push together
or none do, preventing partial state.

### Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `is-upload` | `'false'` | Whether this matrix slot runs PyBuilder's `upload` task |
| `auto-release` | `'true'` | Master switch: enable release automation on `[release]` |
| `auto-release-version` | `'true'` | Strip `.dev` from version when `[release]` detected |
| `auto-github-release` | `'true'` | Create GitHub Release with tag (upload job only) |
| `auto-bump-dev` | `'true'` | Bump to next `.dev` version after release (upload job only) |
| `release-tag-prefix` | `v` | Prefix for release tags (e.g., `v1.0.0`) |
| `release-title-template` | `Release v{version}` | GitHub Release title (`{version}` is replaced) |
| `build-py-path` | `build.py` | Path to `build.py` relative to repo root |
| `github-token` | `${{ github.token }}` | Token for git push and gh CLI |

### Outputs

| Output | Description |
|--------|-------------|
| `is-release` | `'true'` if `[release]` was detected in commit message |
| `release-version` | The release version string, empty if not a release |

### Triggering a Release

Add `[release]` to the merge commit message on push to master:

```
Merge pull request #42 from feature-branch [release]
```

The version in `build.py` should be `X.Y.Z.dev`; the automation strips `.dev` to produce the release
version `X.Y.Z`.

### Explicit Version Override

Use `[release X.Y.Z]` to set a specific release version instead of stripping `.dev`:

```
Merge pull request #42 from feature-branch [release 2.0.0]
```

This is useful for major version bumps or when the version in `build.py` doesn't match the desired release.

### Selective Opt-Out

Disable individual features while keeping others:

```yaml
      - uses: pybuilder/build@master
        with:
          auto-release: 'false'           # Opt out entirely
          auto-github-release: 'false'    # Skip GitHub Release creation
          auto-bump-dev: 'false'          # Skip dev version bump
```

### Permissions

The calling workflow must declare `permissions: contents: write` for the `GITHUB_TOKEN` to be able to
push commits, create tags, and create GitHub Releases. New repositories default to read-only permissions
for `GITHUB_TOKEN`.

```yaml
jobs:
  build:
    permissions:
      contents: write
    steps:
      - uses: pybuilder/build@master
        with:
          is-upload: 'true'
```

### Token Requirements

**Legacy branch protection** (current state of most repos): The default `GITHUB_TOKEN` works without
any override. Required status checks only gate PR merges, not direct pushes. With `enforce_admins: false`
and no push restrictions, `GITHUB_TOKEN` can push directly to master.

**Rulesets** (future migration): Rulesets enforce rules on all pushes, so the default `GITHUB_TOKEN`
will be blocked. Override `github-token` with a token that has bypass permissions:

- **GitHub App token** (recommended): Use `actions/create-github-app-token` to mint a token at workflow
  runtime. Add the app to the ruleset bypass list. Per-org, no PAT, no secrets rotation.
- **Deploy key + SSH**: Create an SSH deploy key with write access. Use `actions/checkout@v5` with
  `ssh-key` for push credentials. The `github-token` input is still needed for `gh release create`.
  Add the deploy key to the ruleset bypass list.
- **PAT**: Legacy fallback, tied to a user account. Add the user to the ruleset bypass list.

```yaml
      - uses: pybuilder/build@master
        with:
          github-token: ${{ steps.app-token.outputs.token }}
```

**No branch protection**: The default `GITHUB_TOKEN` works without any override.

### `version_tool.py`

The release automation uses `version_tool.py`, an AST-based tool bundled with the action that reads and
modifies the `version` variable in `build.py`. It has no external dependencies, uses only the Python
standard library, and is compatible with Python 3.9 through 3.15+. The tool performs static analysis
to prove the version value is deterministic, refusing to operate on files with dynamic versions,
conditional assignments, or other constructs that make the version unprovable.
