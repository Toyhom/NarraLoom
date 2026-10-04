# Contributing

Contributions to the engine, adapters, examples, translations, documentation and starter worlds are welcome.

1. Describe the user-visible behavior or contract you want to change in an issue or pull request.
2. Make a focused change with tests for affected state, visibility, persistence or model boundaries.
3. Run `python scripts/verify.py --distribution`, `python scripts/check_docs.py` and `python scripts/check_public_tree.py`. Add model-backed acceptance when changing model behavior.
4. Explain the final behavior, verification and relevant compatibility effects in the pull request.

Use [developer](guides/developers.md), [research](guides/research.md) and [creator](guides/creators.md) guides for your entry point. UI contributions update all three catalogs with matching keys/parameters. Source or content reused from other projects needs its original notice and pinned provenance.

Keep private keys, model traces, saves, local deployment records and media production materials in ignored runtime/local directories. Public documentation describes how to install, use, extend and test the framework. Contributions use the project's MIT license, with third-party resources retaining their own terms.
