# jellyfin-home-stack — SrPolvoron

## Purpose and architecture
Deploy an existing media stack on the user's Debian host with Docker Compose.
OVH terminates TLS and proxies Jellyfin/Seerr over a private WireGuard tunnel.
Kubernetes learning is independent and out of scope. Keep Debian unchanged.

## Invariants
- Do not implement a custom media player, authentication system or content scraper.
- Base Compose publishes every application exclusively on IPv4 loopback.
- Public media overlay adds Jellyfin and Seerr on the explicit private tunnel IP.
- The admin override may add arr/Bazarr listeners only on that same
  WireGuard IP. Never publish them through Traefik, a wildcard bind or the Internet.
- Bootstrap must finish behind SSH before the public overlay is enabled.
- qBittorrent is owned by the separate `docker-qbittorrent` project. This repository
  must not recreate, configure, back up, stop or publish that container.
- Radarr/Sonarr join the external `media-downloads` network and reach the unambiguous
  alias `qbittorrent-standalone`. Only those two services join that trust boundary.
- The standalone qBittorrent and Radarr/Sonarr mount the same host `DATA_ROOT` as
  `/data`, preserving identical paths and hardlink support without path mappings.
- Media is read-only in Jellyfin. Requests do not automatically create private
  user libraries.
- Bazarr sees only `/data/media`, using the same paths as Radarr/Sonarr so it can
  write subtitle files beside imported media without access to torrent downloads.
- All application processes run non-root; LSIO requires owned, executable /run tmpfs.
- No privileged containers, host networking or Docker socket mounts.
- Compose starts only images pinned to digests. Stable tags are resolver inputs only.
- Persist config locally, separately from media; never silently remove data.
- Existing Jellyfin/Seerr/Radarr/Sonarr/Prowlarr/Bazarr appdata paths are an upgrade
  contract. Never rename, clear, recreate over, or recursively change them.
- Legacy qBittorrent source/lock keys may remain during migration but are not active.
- Operators manage source credentials and application passwords through private UIs.

## Structure and commands
`compose.yaml`: home plus external download network; public/Intel overlays: optional;
`edge/`: optional OVH proxy;
`scripts/stack.py`: stdlib-only operations; `examples/wireguard/`: host tunnel templates.
Run `python3 -m unittest discover -s tests -v` for tool regressions.
Run `python3 tests/check_compose.py` (PyYAML) for static deployment contracts.
Run `./stack config`, `./stack config --public` and `./stack config --target edge`
on a Docker-equipped host after locks exist; then execute README smoke checks.

## Development and delivery
Keep the root README English, maintain the complete Spanish translation at
`docs/README.es.md`, and keep AGENTS English. Prefer stdlib to new runtime dependencies.
Never source/eval .env or invoke subprocess with shell=True. Validate inputs before
filesystem or Docker operations. Reject symlinked managed paths before ownership edits.
Do not add credentials, runtime locks, appdata or private tunnel configs to the ZIP/Git.
Keep source repository and runtime bind paths separate. Do not commit, push or publish
without explicit user authorization. Preserve data and backup/rollback instructions.
Do not claim runtime/E2E validation from a syntax or mocked test. Recheck current
upstream image compatibility after resolving new digests. Do not add CI/CD workflows,
Kubernetes manifests, releases or version bumps unless requested.
