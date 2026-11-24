# Repository release conventions

- Whenever `config.yaml` version is increased, update `CHANGELOG.md` to contain **only** the current version heading and the single entry `- small bugfixes`.
- Do not append old changelog entries or detailed change descriptions to `CHANGELOG.md` or maintain a release-by-release history in `README.md`.
- Update the short current-version line in `README.md` to match `config.yaml` and `CHANGELOG.md`.
- Actual code changes remain available through the Git commit and pull-request history.
