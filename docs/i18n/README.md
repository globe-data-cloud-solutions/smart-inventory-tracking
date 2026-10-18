# Translator round

1. `python scripts/i18n_export.py --locale am --mode review` (or `--mode missing` for Oromo).
2. Send the CSV to the translator; they fill in `new_value` only, leave rows they skip empty.
3. `python scripts/i18n_import.py FILE --locale am --dry-run` — check the applied/skipped/rejected counts.
4. Fix any rejected rows (unknown key or placeholder mismatch), re-export/re-run if needed.
5. `python scripts/i18n_import.py FILE --locale am` — writes `locales/am.json` and runs parity check.
6. `git diff locales/am.json`, then commit.

For Oromo: same steps with `--locale or`. Oromo stays hidden from users (`ENABLED_LOCALES`,
CLAUDE.md §4) until `or.json` is fully translated and reviewed — see RB-6.
