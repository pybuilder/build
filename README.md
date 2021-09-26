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
  build-stable:
    runs-on: ${{ matrix.os }}
    continue-on-error: false
    strategy:
      fail-fast: false
      matrix:
        os:
          - ubuntu-latest
        python-version:
          - '3.10.0-rc.2'
          - '3.9'
          - '3.8'
          - '3.7'
          - '3.6'
    env:
      DEPLOY_BRANCHES: "refs/heads/master"
      DEPLOY_PYTHONS: "3.9"
      DEPLOY_OSES: "Linux"
      TWINE_USERNAME: __token__
      TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}
      GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    steps:
      - shell: bash
        if: |
          contains(env.DEPLOY_OSES, runner.os) &&
          contains(env.DEPLOY_PYTHONS, matrix.python-version) &&
          contains(env.DEPLOY_BRANCHES, github.ref)
        run: |
          echo "PYB_EXTRA_ARGS=upload" >> $GITHUB_ENV
      - uses: pybuilder/build@master
        with:
          python-version: ${{ matrix.python-version }}
          pyb-extra-args: ${{ env.PYB_EXTRA_ARGS }}
          pyb-version: ">=0.13.0.dev0"
```

The above example overrides Python versions using matrix strategy, installs a development version of PyBuilder, and only
runs the `upload` task only when OS, Python version and branch name is the specifies one.

## Reference

### Checkout

Checkout via `actions/checkout@v2` if enabled.

```yaml
  checkout:
    description: 'Do checkout first'
    default: 'true'
```

### Install Python

Python is installed via `actions/setup-python@v2`, unless Homebrew is requested.

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

Python version is expected as at least `major.minor`. If using `actions/setup-python@v2` wildcards can be used
after `major`. If installing with Homebrew, only `major.minor` with no wildcards is supported.

```yaml
  python-version:
    description: 'Python version to use, if installing'
    default: '3.9'
```

#### Python Architecture to Install

This is passed to `actions/setup-python@v2` verbatim and has no effect with Homebrew.

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