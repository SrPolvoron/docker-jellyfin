# Jellyfin Home Stack · SrPolvoron

A private Docker Compose media stack for Debian: Jellyfin playback, Seerr requests,
Radarr/Sonarr automation, Prowlarr indexer management and Bazarr subtitles. Downloads
are provided by the separate `docker-qbittorrent` project through a private external
Docker network. Public Jellyfin and Seerr traffic terminates at Traefik on OVH and
reaches the home server through WireGuard.

[Leer en español](docs/README.es.md)

## Architecture

| Location/project | Services | Exposure |
| --- | --- | --- |
| This home stack | Jellyfin, Seerr | Loopback; optionally home WireGuard IP and OVH Traefik |
| This home stack | Radarr, Sonarr, Prowlarr, Bazarr | Loopback; optionally the home WireGuard IP |
| `docker-qbittorrent` | qBittorrent | Its own loopback/WireGuard policy on port 8081 |
| OVH | Existing Traefik or the optional included Compose | Public 80/443 only |

Only Radarr and Sonarr join the external `media-downloads` network. They reach the
download client at `qbittorrent-standalone:8081`. Both projects mount the same host
`DATA_ROOT` as `/data`, so the download paths are identical and imports can use
hardlinks without Remote Path Mappings:

```text
/srv/media                     -> /data
├── torrents/standalone/movies -> Radarr downloads
├── torrents/standalone/tv     -> Sonarr downloads
└── media
    ├── movies                 -> Jellyfin movie library
    └── tv                     -> Jellyfin series library
```

qBittorrent is not defined, started, stopped, updated, published or backed up by this
repository. Its appdata remains independently owned by `docker-qbittorrent`.

## Persistence contract

The following host directories contain the state that must be preserved:

```text
/srv/jellyfin-home/appdata/jellyfin
/srv/jellyfin-home/appdata/seerr
/srv/jellyfin-home/appdata/radarr
/srv/jellyfin-home/appdata/sonarr
/srv/jellyfin-home/appdata/prowlarr
/srv/jellyfin-home/appdata/bazarr
```

Updating this repository does not rename, clear or recreate those directories.
`prepare` only creates missing paths and refuses to take ownership of an existing
directory owned by somebody else. Backups include those six appdata directories,
`.env` and `images.lock.env`; they exclude media, downloads and cache.

## Requirements

- Debian or another Linux host, Python 3.10+, Docker Engine 28+ and Compose 2.24+.
- One non-root PUID/PGID used by both projects.
- Local appdata storage and a shared data root, normally `/srv/media`.
- The standalone qBittorrent project deployed first with its `--media` overlay.
- SSH; optionally a host WireGuard tunnel and two domains for Jellyfin/Seerr.

## Clean installation

Configure the standalone qBittorrent project first. Its `.env` should contain the
same PUID, PGID, data root and external network name used here:

```dotenv
PUID=1000
PGID=1000
DATA_ROOT=/srv/media
SHARED_NETWORK=media-downloads
WEBUI_PORT=8081
```

From the qBittorrent repository:

```bash
./stack check
sudo ./stack prepare
./stack lock
./stack network-create
./stack up --media
# Use --media --vpn instead if its Web UI must also listen on WireGuard.
```

Change its temporary password and run `./stack categories` there. Then initialize
this repository:

```bash
chmod +x stack
./stack init
nano .env
./stack check
sudo ./stack prepare
./stack lock
./stack config
./stack up
./stack status
```

Set the same values in this project's `.env`:

```dotenv
PUID=1000
PGID=1000
DATA_ROOT=/srv/media
SHARED_NETWORK=media-downloads
```

Before `up`, the tool verifies that the external network is a Docker bridge, the
standalone movie/TV download directories exist with the expected ownership, and no
old qBittorrent container remains attached to this Compose project.

## Safe migration from the former embedded qBittorrent

This is an intentional service split. Jellyfin, Seerr, Radarr, Sonarr, Prowlarr and
Bazarr keep their current appdata. Media and torrent payloads are not required for
the migration, but do not delete them until the new flow has been tested.

Perform the first commands with the **currently deployed old repository**, before
copying the updated files:

```bash
cd /path/to/current/jellyfin-home-stack
sudo mkdir -p /srv/backups/jellyfin
sudo ./stack backup --output /srv/backups/jellyfin/before-qbittorrent-split.tar.gz
./stack down
sudo tar -tzf /srv/backups/jellyfin/before-qbittorrent-split.tar.gz
```

The old `down` removes containers and Compose networks only; bind-mounted appdata,
downloads and media remain on disk. The pre-migration archive also contains the old
qBittorrent configuration because it was created by the old version.

Next:

1. Deploy `docker-qbittorrent` with `DATA_ROOT=/srv/media`, its separate
   `CONFIG_ROOT=/srv/qbittorrent/config`, and `SHARED_NETWORK=media-downloads`.
2. Run its `prepare`, `lock`, `network-create`, `up --media` and `categories` commands.
3. Replace only this repository's tracked project files. Preserve its existing `.env`
   and `images.lock.env`.
4. Add `SHARED_NETWORK=media-downloads` to the existing `.env`. Legacy
   `QBITTORRENT_SOURCE_IMAGE` and `QBITTORRENT_IMAGE` lines may remain temporarily;
   they are accepted for compatibility but are not used.
5. Run the normal `check`, `prepare`, `lock`, `config` and `up` commands above.
6. In both Radarr and Sonarr, edit the existing qBittorrent download client:

   | Field | Value |
   | --- | --- |
   | Host | `qbittorrent-standalone` |
   | Port | `8081` |
   | SSL | Disabled |
   | Category | `movies` in Radarr; `tv` in Sonarr |
   | Credentials | The new standalone qBittorrent credentials |

   Keep Remote Path Mappings empty and press **Test**.

Do not copy the old qBittorrent `/config` into the new project while either instance
is running. Keep the old directory and backup until a test request downloads, imports,
appears in Jellyfin and obtains subtitles successfully.

## Private access

Open all local panels through one SSH connection:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 8096:127.0.0.1:8096 -L 5055:127.0.0.1:5055 \
  -L 7878:127.0.0.1:7878 -L 8989:127.0.0.1:8989 \
  -L 9696:127.0.0.1:9696 -L 6767:127.0.0.1:6767 \
  -L 8081:127.0.0.1:8081 casa
```

| Application | Laptop URL |
| --- | --- |
| Jellyfin | `http://127.0.0.1:8096` |
| Seerr | `http://127.0.0.1:5055` |
| Radarr | `http://127.0.0.1:7878` |
| Sonarr | `http://127.0.0.1:8989` |
| Prowlarr | `http://127.0.0.1:9696` |
| Bazarr | `http://127.0.0.1:6767` |
| qBittorrent (separate project) | `http://127.0.0.1:8081` |

Complete account and application setup with [docs/CONFIGURACION.md](docs/CONFIGURACION.md).

## WireGuard and public access

Follow [docs/ACCESO_OVH.md](docs/ACCESO_OVH.md). Once accounts and the tunnel have
been verified:

```bash
./stack config --public
./stack up --public --accounts-configured
./stack edge-config --accounts-configured
```

The public overlay exposes Jellyfin and Seerr on the home WireGuard IP for the OVH
proxy. The admin override adds Radarr, Sonarr, Prowlarr and Bazarr to that same private
IP. It does not publish qBittorrent; that project controls its own optional `--vpn`
listener. None of the admin panels receives a Traefik router or public subdomain.

Keep `--public` on later `up` commands to retain these WireGuard listeners.

## Backups, updates and recovery

Create a consistent configuration backup before changes:

```bash
sudo ./stack backup --output /srv/backups/jellyfin/media-2026-10-14.tar.gz
```

The command stops only currently running services from this repository, creates a
0600 archive, and restarts only those services. Back up qBittorrent from its own
repository. Store both archives encrypted and off-host because they contain API keys,
sessions and application credentials.

Update deliberately:

```bash
./stack lock --refresh
./stack config --public
./stack up --public --accounts-configured
```

The previous image lock is retained. Image rollback alone cannot reverse application
database migrations; restore the matching appdata backup when required. Do not use
`docker compose down -v`, `--remove-orphans`, or recursive deletion as part of this
migration.

## Validation

```bash
python3 -m unittest discover -s tests -v
python3 tests/check_compose.py       # Requires PyYAML
python3 -m py_compile scripts/stack.py tests/*.py
./stack config
./stack config --public
```

Local tests validate configuration parsing, immutable image locks, persistence and
backup boundaries, Compose networks, private bindings and the external download-client
contract. Production confidence still requires a real Docker start on the Debian host,
Radarr/Sonarr download-client tests and one legal end-to-end download/import check.

See [docs/VALIDACION.md](docs/VALIDACION.md) for the acceptance checklist. This
repository is MIT-licensed; each packaged application retains its own license.
