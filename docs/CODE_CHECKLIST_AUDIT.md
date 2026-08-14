# AutoTidy Code Checklist Audit

> Updated for 2.0.0 (Rust + Tauri). Items describing the Python implementation
> refer to the retired 1.5.0 engine, which is kept under
> [`legacy/`](../legacy/README.md) as the reference the rewrite is verified
> against — not as shipping code.

Checklist source: https://imageomics.github.io/Imageomics-guide/wiki-guide/Code-Checklist/
Audit date: 2026-04-20

## Required Files

- [x] License file present: `LICENSE` (MPL-2.0)
- [x] README present with overview, installation, and usage: `README.md`
- [x] Dependency specification present: `Cargo.toml` and `package.json` (the
      shipping Rust + Tauri app); `legacy/pyproject.toml` and
      `legacy/requirements.txt` for the retired 1.5.0 reference engine
- [x] Git ignore rules present: `.gitignore`
- [x] Citation metadata present: `CITATION.cff`

## Data-Related

- [ ] Preprocessing code
- [ ] Dataset card links
- [ ] Train/test split documentation

Status: Not applicable for current scope. AutoTidy is a desktop utility, not a data-training repository.

## Model-Related

- [ ] Training code
- [ ] Inference/evaluation code
- [ ] Model weights/model card links

Status: Not applicable for current scope. AutoTidy is not a model repository.

## General Information

- [x] Clear repository structure with tests and docs
- [x] Function and module comments/docstrings used in core modules
- [x] Reproducibility statement added in README (deterministic rule processing)

## Security Considerations

- [x] No hardcoded API keys or credentials found in source files
- [x] Sensitive data guidance documented in README

## Best Practices

### Reproducibility

- [x] Git repository with source history
- [x] Modular code layout (`config_manager`, `worker`, `utils`, UI modules)
- [ ] Notebook-based reproducibility examples

Notebook item status: Not applicable for this desktop application workflow.

### Code Review and Maintenance

- [x] Pull request workflow implied via GitHub + README contribution section
- [x] Issue tracking supported by GitHub repository features
- [x] Versioning present (`APP_VERSION`, `pyproject.toml`)

### Installation and Dependencies

- [x] Setup instructions in README
- [x] Virtual environment recommendation added in README
- [x] Dependencies pinned/ranged in `requirements.txt` and `pyproject.toml`

## More Advanced Development

### Documentation

- [x] User/developer documentation in README and docs folder
- [x] Example usage commands included in README
- [x] Configuration file approach used (`config.json` managed by `ConfigManager`)

### Code Quality

- [x] Project generally follows PEP 8 style conventions
- [x] Logging is used in runtime modules (replaced print diagnostics in core paths)
- [x] Error handling present around filesystem and startup operations

### Testing

- [x] Unit tests present under `crates/*/src` and `src-tauri/src` (251 tests)
- [x] Reference-engine tests retained under `legacy/tests/` (76 tests)
- [x] Differential parity harnesses under `tools/parity/`, run in CI
- [x] Automated test workflow: `.github/workflows/ci.yml`

### Code Distribution and Deployment

- [x] Packaging/build metadata present (`Cargo.toml`, `src-tauri/tauri.conf.json`)
- [x] Release workflow present (`.github/workflows/release.yml`)

## Follow-up Recommendations

- Add a small changelog file for release notes.
- Optionally add Ruff configuration and a lint CI job for automated style checks.
- Add API-style docs if internal architecture docs are needed for contributors.
