# jellyfin-home-stack — SrPolvoron

## Purpose and architecture
Deploy an existing media stack on the user's Debian host with Docker Compose.
OVH terminates TLS and proxies Jellyfin/Seerr over a private WireGuard tunnel.
Kubernetes learning is independent and out of scope. Keep Debian unchanged.

## Invariants
- Do not implement a custom media player, authentication system or content scraper.
- Base Compose publishes every application exclusively on IPv4 loopback.
- Public overlay adds only Jellyfin and Seerr on the explicit private tunnel IP.
- Never expose arr/qBittorrent administration through OVH or a wildcard bind.
- Bootstrap must finish behind SSH before the public overlay is enabled.
- Media is read-only in Jellyfin; qBittorrent only mounts its downloads subtree.
- Radarr/Sonarr see downloads and library under one `/data` bind, on one filesystem
  for hardlinks. Requests do not automatically create private user libraries.
- All application processes run non-root; LSIO requires owned, executable /run tmpfs.
- No privileged containers, host networking or Docker socket mounts.
- Compose starts only images pinned to digests. Stable tags are resolver inputs only.
- Persist config locally, separately from media; never silently remove data.
- Operators manage source credentials and application passwords through private UIs.

## Structure and commands
`compose.yaml`: home; public/Intel overlays: optional; `edge/`: optional OVH proxy;
`scripts/stack.py`: stdlib-only operations; `examples/wireguard/`: host tunnel templates.
Run `python3 -m unittest discover -s tests -v` for tool regressions.
Run `python3 tests/check_compose.py` (PyYAML) for static deployment contracts.
Run `./stack config`, `./stack config --public` and `./stack config --target edge`
on a Docker-equipped host after locks exist; then execute README smoke checks.

## Development and delivery
Keep README Spanish and AGENTS English. Prefer stdlib to new runtime dependencies.
Never source/eval .env or invoke subprocess with shell=True. Validate inputs before
filesystem or Docker operations. Reject symlinked managed paths before ownership edits.
Do not add credentials, runtime locks, appdata or private tunnel configs to the ZIP/Git.
Keep source repository and runtime bind paths separate. Do not commit, push or publish
without explicit user authorization. Preserve data and backup/rollback instructions.
Do not claim runtime/E2E validation from a syntax or mocked test. Recheck current
upstream image compatibility after resolving new digests. Do not add CI/CD workflows,
Kubernetes manifests, releases or version bumps unless requested.
