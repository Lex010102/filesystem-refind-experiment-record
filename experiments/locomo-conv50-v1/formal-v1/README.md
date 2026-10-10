# formal-v1

`manifest.json` is the machine-readable source of truth for the frozen main-40
experiment. It is content-addressed and must not be edited in place.

Verify it offline from the repository root:

```bash
python3 -m fs_memory_lab.formal_v1_cli --repo-root . verify
```

The freeze does not contain API credentials or main-40 outputs. Any substantive
method correction requires a new formal version and a complete rerun of affected
conditions; records from different versions must never be mixed.
