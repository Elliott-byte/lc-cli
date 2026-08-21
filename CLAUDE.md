# CLAUDE.md

Check `AGENTS.md` first — it is the map of this repo: what each module owns,
the invariants that are not visible from inside any one file, the testing
patterns, and the shipping checklist (version bump every commit, narrative
messages, regression tests proven against the old code).

The short version, if you read nothing else:

- `~/.lc/review.json` is user data; the sync clone and `cache.db` are
  disposable. Never regenerate the deck.
- Every commit bumps the version in `pyproject.toml` + `lc/__init__.py`.
  Releases are tags pushed from the maintainer's machine — never reuse a
  version number.
- Two machines push here: fetch before pushing.
- This repo's git identity is repo-local (a noreply address) — do not commit
  with the global identity.
