# Repository Documentation & UX Standards Guide

---

> **Note for Agents:**
> This document defines the full standard for repository documentation, layout, and deployment.
> Read and apply this pattern **exactly** when creating or updating documentation for other repositories.
>
> **Scope:** Python open-source packages hosted on GitHub + PyPI, with MkDocs Material documentation sites.
> **Output files this guide governs:**
> - `README.md` (root)
> - `CONTRIBUTING.md` (root)
> - `CHANGELOG.md` (root)
> - `mkdocs.yml` (root)
> - `.github/workflows/docs.yml`
> - `.github/workflows/tests.yml`
> - `.github/ISSUE_TEMPLATE/bug_report.yml`
> - `.github/ISSUE_TEMPLATE/feature_request.yml`
> - `.github/pull_request_template.md`

---

## 1. README.md Blueprint

Every repository must have a structured `README.md` at the root. Layout prioritizes **immediate clarity**, **quick value validation (the Hook)**, **visuals**, and **progressive disclosure of complexity**.

### Template Structure

```markdown
# [Project Name]

[Badges Block — see Section 5]

**[The Hook — one bold sentence: the core problem solved and how]**

[1–2 paragraph overview: what it does, target audience, key data sources/integrations.
If a peer-reviewed paper exists, cite it inline here: "Introduced in [Author et al., Year](doi_link)."]

[Primary CTA link to full documentation site]

[Primary Preview Image/GIF — shows library output, report dashboard, or final visual.
User must see the final product without scrolling.]

## Why [Project Name]?

[Provide a value comparison table]

| Common Approach | [Project Name] Approach |
| --- | --- |
| [Limitation 1] | [Solves 1] |
| [Limitation 2] | [Solves 2] |

[Conceptual diagram / visual explaining value proposition]

## Start Quickly

[Install and run in < 30 seconds]

```bash
pip install [project-name]
```

Run demo/CLI:
```bash
[project-name] demo --out output/demo.csv
```

Or write simple code:
```python
# Minimal example — copy-paste ready
import package
result = package.run()
print(result)
```

## Advanced Usage

[Optional dependencies, data fetchers, alternative interfaces]

```bash
pip install "project-name[extra]"
```

```python
# Advanced API snippet
```

## Accessors / Access Patterns
[If library integrates with pandas or xarray, document accessors here]
```python
import package
import pandas as pd

df.package.method()
```

## Command Line Interface
[Key CLI options with clean syntax]

```bash
project-name run --config config.yaml
```

## Used In

[Surface social proof. Include paper DOIs, talks, and downstream projects.]

- [Author et al. (Year), *Title*, Journal](https://doi.org/...)
- [Conference / workshop talk](link)
- [Downstream project using this library](link)

## Documentation Map
- Quick start: [Link]
- Methods & Workflow: [Link]
- API Reference: [Link]

## Development & Testing

```bash
git clone https://github.com/user/project-name.git
cd project-name
pip install -e ".[dev,docs,all]"
pytest
```

## Citation

If you use [Project Name] in your research, please cite:

```bibtex
@software{authorYYYY,
  author    = {Author, Name},
  title     = {Project Name},
  year      = {YYYY},
  doi       = {10.5281/zenodo.XXXXXXX},
  url       = {https://github.com/username/project-name}
}
```

## License
MIT License — see [LICENSE](LICENSE) for details.
```

---

## 2. Key Design & UX Guidelines

1. **The Hook:** Never start with "This repository contains..." or "Welcome to...". State the problem and how it is solved. Example: *"Hydrological seasons do not always follow the calendar."*
2. **Visuals First:** Place output/dashboard image directly under the Hook. A user must see the final product without scrolling.
3. **Comparison Tables:** Side-by-side "Common/Static Approach" vs. "[Project] Dynamic Approach". Makes technical benefit immediately obvious.
4. **Copy-to-Clipboard Code:** All code blocks must be self-contained and copy-pasteable. Never leave placeholders in runnable blocks.
5. **No Placeholder Images:** All linked images must exist. Generate valid preview SVGs, PNGs, or diagrams with tools.
6. **Trust Signals:** Surface credibility early. If a peer-reviewed paper exists, link the DOI in the hook paragraph. Include Zenodo DOI badge. Add "Used In" section.
7. **PyPI README Sync:** In `pyproject.toml`, set `readme = "README.md"` under `[project]` so PyPI renders the same README. Verify the PyPI page renders correctly after first publish.

---

## 3. MkDocs Material Setup

Use **MkDocs Material** for the documentation website. Create `mkdocs.yml` in the root of the repository.

### Configuration Template (`mkdocs.yml`)

```yaml
site_name: ProjectName
site_description: Short project description focusing on value
site_url: https://username.github.io/project-name/
repo_url: https://github.com/username/project-name
repo_name: username/project-name

theme:
  name: material
  features:
    - content.code.copy          # Copy button on all code blocks
    - content.tabs.link          # Linkable content tabs
    - navigation.instant         # SPA-like instant navigation
    - navigation.sections        # Group navigation links
    - navigation.expand          # Auto-expand nav sections
    - navigation.top             # Back to top button
    - search.highlight           # Highlight search terms in results
    - search.suggest             # Live search suggestions
    - announce.dismiss           # Dismissable announcement bar
  palette:
    - scheme: default            # Light mode
      primary: blue
      accent: teal
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - scheme: slate              # Dark mode
      primary: blue
      accent: teal
      toggle:
        icon: material/brightness-4
        name: Switch to light mode

extra:
  social:
    - icon: fontawesome/brands/github
      link: https://github.com/username/project-name
    - icon: fontawesome/brands/python
      link: https://pypi.org/project/project-name/

nav:
  - Home: index.md
  - Quick Start: quickstart.md
  - Methods & Workflow: methods.md
  - Algorithm: algorithm.md
  - Configuration: configuration.md
  - Outputs & Metrics: outputs.md
  - API Reference: api.md
  - Citation: citation.md

plugins:
  - search
  - mkdocstrings:               # Auto-generate API docs from docstrings
      handlers:
        python:
          options:
            members_order: source
            show_source: false

markdown_extensions:
  - admonition                  # !!! note/tip/warning boxes
  - attr_list                   # Add HTML attributes to markdown
  - md_in_html                  # Render markdown inside HTML
  - tables                      # Styled markdown tables
  - toc:
      permalink: true           # Direct anchor link icon on headings
  - pymdownx.arithmatex:        # LaTeX math notation
      generic: true
  - pymdownx.details            # Collapsible detail blocks (??? note)
  - pymdownx.superfences        # Nested and tabbed code blocks
  - pymdownx.tabbed:            # Content tabs
      alternate_style: true
```

---

## 4. GitHub Actions CI/CD

### 4a. Documentation Workflow (`.github/workflows/docs.yml`)

Automatically builds and deploys the MkDocs site to GitHub Pages on every push to `main` that touches docs-related files.

```yaml
name: Deploy documentation

on:
  push:
    branches: [main]
    paths:
      - docs/**
      - mkdocs.yml
      - pyproject.toml
      - .github/workflows/docs.yml
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install docs dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[docs]"

      - name: Build site
        run: mkdocs build --strict

      - name: Configure GitHub Pages
        uses: actions/configure-pages@v5

      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    permissions:
      pages: write
      id-token: write
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

### 4b. Test Workflow (`.github/workflows/tests.yml`)

Required so the Tests badge (Section 5) has a source. Adapt matrix versions to project's supported range.

```yaml
name: Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Run tests
        run: pytest --cov=src --cov-report=xml

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v4
        with:
          files: ./coverage.xml
          fail_ci_if_error: false
```

---

## 5. Professional Badges Standard

Place a clean badges block at the top of README, immediately after the title. Order: health → docs → package → academic.

```markdown
[![Tests](https://github.com/username/project/actions/workflows/tests.yml/badge.svg)](https://github.com/username/project/actions/workflows/tests.yml)
[![Coverage](https://codecov.io/gh/username/project/branch/main/graph/badge.svg)](https://codecov.io/gh/username/project)
[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://username.github.io/project/)
[![PyPI version](https://img.shields.io/pypi/v/project.svg)](https://pypi.org/project/project/)
[![Python versions](https://img.shields.io/pypi/pyversions/project.svg)](https://pypi.org/project/project/)
[![Downloads](https://img.shields.io/pypi/dm/project.svg)](https://pypi.org/project/project/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/username/project/blob/main/LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)
```

**Badge guidance:**
- `Tests` — always include; source must be `tests.yml` (see Section 4b)
- `Coverage` — add after configuring Codecov (free for public repos)
- `DOI` — register repo on [zenodo.org](https://zenodo.org) linked to GitHub; gets DOI on each release
- `Downloads` — shows adoption signal; omit if pre-release / not yet on PyPI
- `JOSS` — add `[![status](https://joss.theoj.org/papers/.../badge.svg)]` if published in JOSS

---

## 6. CONTRIBUTING.md Template

Create `CONTRIBUTING.md` at the root. Reduces friction for external contributors and signals an active, welcoming project.

```markdown
# Contributing to [Project Name]

Thank you for your interest in contributing!

## Getting Started

1. Fork the repository and clone your fork.
2. Install development dependencies:
   ```bash
   pip install -e ".[dev,docs]"
   ```
3. Create a feature branch:
   ```bash
   git checkout -b feat/your-feature
   ```

## Development Workflow

- Run tests: `pytest`
- Run tests with coverage: `pytest --cov=src`
- Format code: `ruff format .`
- Lint: `ruff check .`
- Type check: `mypy src/`

## Submitting Changes

- Open a pull request against `main`.
- Fill in the PR template.
- Ensure all CI checks pass before requesting review.
- Reference related issues with `Closes #N`.

## Reporting Bugs

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml).

## Requesting Features

Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.yml).

## Code Style

This project uses [ruff](https://docs.astral.sh/ruff/) for formatting and linting.
Run `ruff format . && ruff check .` before committing.

## License

By contributing, you agree your contributions will be licensed under the MIT License.
```

---

## 7. GitHub Issue & PR Templates

### Bug Report (`.github/ISSUE_TEMPLATE/bug_report.yml`)

```yaml
name: Bug Report
description: File a bug report
title: "[Bug]: "
labels: ["bug"]
body:
  - type: markdown
    attributes:
      value: "Thanks for taking the time to fill out this bug report!"
  - type: input
    id: version
    attributes:
      label: Package version
      placeholder: "e.g. 0.3.1"
    validations:
      required: true
  - type: textarea
    id: description
    attributes:
      label: Describe the bug
      placeholder: A clear description of what the bug is.
    validations:
      required: true
  - type: textarea
    id: reproduce
    attributes:
      label: Steps to reproduce
      placeholder: |
        ```python
        import package
        # minimal reproducible example
        ```
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Expected behavior
    validations:
      required: true
  - type: textarea
    id: environment
    attributes:
      label: Environment
      placeholder: |
        - OS: [e.g. Ubuntu 22.04]
        - Python: [e.g. 3.11]
        - Package version: [e.g. 0.3.1]
```

### Feature Request (`.github/ISSUE_TEMPLATE/feature_request.yml`)

```yaml
name: Feature Request
description: Suggest an idea or enhancement
title: "[Feature]: "
labels: ["enhancement"]
body:
  - type: textarea
    id: problem
    attributes:
      label: Is your feature request related to a problem?
      placeholder: A clear description of the problem or use case.
    validations:
      required: true
  - type: textarea
    id: solution
    attributes:
      label: Describe the solution you'd like
    validations:
      required: true
  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives considered
```

### Pull Request Template (`.github/pull_request_template.md`)

```markdown
## Summary

Briefly describe the changes in this PR.

## Related Issues

Closes #

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Refactor / performance improvement
- [ ] Breaking change

## Checklist

- [ ] Tests pass locally (`pytest`)
- [ ] New tests added for new behavior
- [ ] Docstrings updated
- [ ] `CHANGELOG.md` updated
```

---

## 8. CHANGELOG.md Standard

Maintain a `CHANGELOG.md` at the root following [Keep a Changelog](https://keepachangelog.com) format. Users and downstream consumers check this to assess project activity and stability.

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
### Changed
### Fixed
### Deprecated
### Removed

## [0.1.0] — YYYY-MM-DD

### Added
- Initial release.
```

**Guidance:**
- Update `[Unreleased]` section with every merged PR.
- On release: rename `[Unreleased]` → `[X.Y.Z] — YYYY-MM-DD`, open new `[Unreleased]`.
- Link versions at bottom: `[0.1.0]: https://github.com/username/project/releases/tag/v0.1.0`

---

## 9. Trust Signals Checklist

Before considering a repo "SOTA-ready", verify:

- [ ] DOI registered via [Zenodo](https://zenodo.org) (link GitHub → auto-mint DOI on each release)
- [ ] Zenodo DOI badge in README
- [ ] Codecov badge showing coverage %
- [ ] Citation block (BibTeX) in README + `CITATION.cff` in root
- [ ] Paper DOI linked in hook paragraph if peer-reviewed
- [ ] "Used In" section populated (even one downstream project/paper)
- [ ] PyPI renders README correctly (`pip install twine && twine check dist/*`)
- [ ] `pyproject.toml` has `readme = "README.md"` under `[project]`
- [ ] All CI badges are green before first public announcement
