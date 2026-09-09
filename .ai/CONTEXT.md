# AI Context Route

```yaml
schema_version: 1
context_repo: https://github.com/madebycli/master-context
project_id: nix-config
source_repo: https://github.com/madebycli/nix-config
context_root: projects/nix-config/
entrypoint: projects/nix-config/INDEX.md
```

## Mandatory AI behavior

This file is the authoritative context route for this repository.

1. Validate this exact mapping against `REGISTRY.yaml` when available.
2. Read the declared entrypoint before loading additional project context.
3. Do not guess another context path or scan sibling project folders.
4. Follow only task-relevant graph links from this project.
5. Cross-project context requires an explicit cross-project link or explicit user instruction.
6. Durable private AI context belongs in `madebycli/master-context`.
7. Before declaring project work complete, reconcile the master context with the verified repository state.
8. Archive reusable prompts, plans and handoffs under `prompts/nix-config/` when write access is available.
