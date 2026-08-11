# Repository Guidelines

## Project Structure & Module Organization

`main.py` starts Uvicorn; `src/main.py` creates the FastAPI app and lifecycle. HTTP routes live in `src/api/`, shared configuration, authentication, database, and models in `src/core/`, and browser integrations, scheduling, and `*_executor.py` implementations in `src/services/`. Admin pages and assets are under `static/`; API reference pages are in `api-docs/`. `config/setting_example.toml` documents settings, `data/` holds runtime state, and `scripts/` contains maintenance and release utilities.

## Build, Test, and Development Commands

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

This installs dependencies and starts the service using the host and port in `config/setting.toml`.

- `python -m compileall -q main.py src scripts` checks Python syntax before review.
- `powershell -ExecutionPolicy Bypass -File .\fpbrowser2api_service.ps1 status` inspects the managed Windows service; it also accepts `start`, `restart`, and `stop`.
- `python scripts\build_public_pyc_release.py -O ..\fpbrowser2api_public` creates the CPython-version-specific public release in a dedicated sibling directory.

## Coding Style & Naming Conventions

Use four-space indentation and PEP 8. Group imports as standard library, third-party, then local modules. Prefer type hints and `async` functions for database, HTTP, and browser I/O. Use `snake_case` for modules and functions, `PascalCase` for classes and Pydantic models, and `UPPER_SNAKE_CASE` for constants. New tasks should follow `<provider>_task_executor.py` or `<provider>_workflow_executor.py`. No formatter or linter is configured; match adjacent code and avoid unrelated reformatting.

## Testing Guidelines

No automated suite or coverage gate is committed. Run `compileall`, start the app, open `/docs`, and exercise the affected authenticated endpoint or admin workflow. Browser-executor changes require a manual run against the relevant configured window and inspection of task status and logs. New pytest files should use `tests/test_<module>.py` and `test_<behavior>` names, temporary databases, and mocked external services.

## Commit & Pull Request Guidelines

History favors short Chinese summaries and occasional scoped subjects such as `fix(proxy): ...`. Keep commits focused; prefer `fix(scope): summary` or `feat(scope): summary`. Pull requests should explain behavior, link issues, identify API/configuration/database impacts, and list validation. Include screenshots for `static/` UI changes and note required browser, account, or proxy setup.

## Git Remote Workflow

The working branch is `github`. Treat `https://github.com/lakysir/fpbrowser2api.git` as the read-only source repository (`upstream`) and `git@github.com:githubshansheng/fpbrowser2api.git` as the writable fork (`origin`). The branch configuration must keep pulls and pushes separate:

```powershell
git config branch.github.remote upstream
git config branch.github.merge refs/heads/github
git config branch.github.pushRemote origin
```

Before synchronizing, run `git status --short --branch` and `git remote -v`. Use `git pull --rebase` to update from `upstream/github`, then use `git push` to publish to `origin/github`. Never push to `upstream` or force-push unless the user explicitly authorizes it. Do not discard, stash, commit, or overwrite local runtime changes merely to make a pull succeed; inspect and preserve them first.

## Security & Configuration

Never commit real API keys, admin passwords, bridge tokens, OSS credentials, proxies, cookies, or account data. Review diffs to `config/setting.toml` and `data/fpbrowser.db` carefully and exclude incidental runtime changes. Treat generated logs, analysis output, and release directories as local artifacts.
