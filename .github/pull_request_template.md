## Summary

<!-- What does this change do and why? Link related issues (e.g. "Closes #123"). -->

## OpenSpec change

<!-- The change under openspec/changes/<change-id>/ this PR implements, or "n/a" for chores/docs. -->

- Change: `openspec/changes/<change-id>`
- Tasks completed: <!-- e.g. 2.1, 2.2 -->

## Type of change

- [ ] `feat`: new capability
- [ ] `fix`: bug fix
- [ ] `refactor` / `perf`: no behaviour change
- [ ] `docs`: documentation only
- [ ] `build` / `ci` / `chore`: tooling, packaging, pipeline
- [ ] Breaking change (API contract under `/v1` or a non-backward-compatible migration)

## Testing

<!-- How was this verified? Paste relevant commands and output. -->

- [ ] `make lint typecheck test`
- [ ] `make test-postgres` (when touching persistence or migrations)
- [ ] Manual check (describe):

## Checklist

- [ ] Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
- [ ] Tests added or updated; coverage stays at or above 90%
- [ ] `openspec validate --all --strict` passes and completed tasks are ticked in `tasks.md`
- [ ] New migrations are backward compatible with the running release (see `CONTRIBUTING.md`)
- [ ] Docs and `CHANGELOG.md` (`[Unreleased]`) updated where user-visible
- [ ] No secrets, credentials or personal data committed
