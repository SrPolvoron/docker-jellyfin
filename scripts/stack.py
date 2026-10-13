#!/usr/bin/env python3
"""Small, explicit Docker operations. Runtime: Python 3.10+ standard library."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
HOME_SERVICES = ("jellyfin", "seerr", "radarr", "sonarr", "prowlarr", "bazarr", "qbittorrent")
REPOSITORIES = {
    "JELLYFIN": "jellyfin/jellyfin",
    "SEERR": "ghcr.io/seerr-team/seerr",
    "RADARR": "lscr.io/linuxserver/radarr",
    "SONARR": "lscr.io/linuxserver/sonarr",
    "PROWLARR": "lscr.io/linuxserver/prowlarr",
    "BAZARR": "lscr.io/linuxserver/bazarr",
    "QBITTORRENT": "lscr.io/linuxserver/qbittorrent",
    "TRAEFIK": "traefik",
}
KNOWN_KEYS = {
    "COMPOSE_PROJECT_NAME", "TZ", "PUID", "PGID", "APPDATA_ROOT", "DATA_ROOT",
    "HOME_WG_IP", "OVH_WG_IP", "WG_INTERFACE", "JELLYFIN_DOMAIN", "SEERR_DOMAIN",
    "TRAEFIK_HTTP_ENTRYPOINT", "TRAEFIK_HTTPS_ENTRYPOINT", "TRAEFIK_CERT_RESOLVER",
    "ACME_EMAIL", "RENDER_GID",
} | {f"{name}_SOURCE_IMAGE" for name in REPOSITORIES}
LOCK_KEYS = {f"{name}_IMAGE" for name in REPOSITORIES}


class ConfigError(Exception):
    pass


def read_env(path: Path, keys: set[str]) -> dict[str, str]:
    """Deliberately literal subset of dotenv; never source/eval configuration."""
    if path.is_symlink():
        raise ConfigError(f"Se rechaza un enlace simbólico: {path.name}")
    if not path.is_file():
        raise ConfigError(f"Falta {path.name}; consulta ./stack init o ./stack lock")
    values: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key not in keys or key in values:
            raise ConfigError(f"{path.name}:{lineno}: clave desconocida, repetida o inválida")
        if not value or any(c.isspace() for c in value) or any(c in value for c in "\"'`$#\\"):
            raise ConfigError(f"{path.name}:{lineno}: usa un valor literal sin comillas ni espacios")
        values[key] = value
    return values


def check_path(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ConfigError(f"Ruta con enlace simbólico no admitida: {path}")


def storage_path(value: str) -> Path:
    path = Path(value)
    if (not path.is_absolute() or len(path.parts) < 3 or ".." in path.parts
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value)):
        raise ConfigError("Almacenamiento: ruta absoluta concreta, sin espacios ni '..'")
    forbidden = ("/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/proc",
                 "/sys", "/dev", "/boot", "/run", "/var/lib/docker",
                 "/var/lib/containerd", "/var/lib/kubelet", "/var/lib/rancher")
    if any(path == Path(p) or Path(p) in path.parents for p in forbidden):
        raise ConfigError("No se permite usar una ruta del sistema para almacenamiento")
    check_path(path)
    return path


def related(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def private_ipv4(value: str) -> str:
    try:
        addr = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise ConfigError("IP del túnel inválida") from exc
    if not any(addr in ipaddress.ip_network(net) for net in
               ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
        raise ConfigError("Las IP del túnel deben ser privadas RFC1918 y concretas")
    return str(addr)


def domain(value: str, *, real: bool = False) -> str:
    if len(value) > 253 or value != value.lower() or "." not in value:
        raise ConfigError("Subdominio inválido: usa minúsculas y un FQDN")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
           for label in value.split(".")):
        raise ConfigError("Subdominio inválido")
    if real and (value.endswith((".example.com", ".example.org", ".example.net", ".invalid"))
                 or value in ("example.com", "example.org", "example.net")):
        raise ConfigError("Sustituye los dominios de ejemplo antes de publicar")
    return value


def image_repo(value: str) -> str:
    if "@" in value:
        return value.split("@", 1)[0]
    return value.rsplit(":", 1)[0]


def valid_image(value: str, name: str, *, pinned: bool) -> bool:
    repo = REPOSITORIES[name]
    aliases = {repo}
    if repo.startswith("lscr.io/"):
        aliases.add(repo.replace("lscr.io/", "ghcr.io/", 1))
    if repo in ("traefik", "jellyfin/jellyfin"):
        aliases |= {f"docker.io/{repo}", f"docker.io/library/{repo}"}
    if pinned:
        return any(re.fullmatch(re.escape(r) + r"@sha256:[0-9a-f]{64}", value)
                   for r in aliases)
    return (image_repo(value) == repo and
            bool(re.fullmatch(re.escape(repo) + r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}|@sha256:[0-9a-f]{64})", value)))


def load_config() -> dict[str, str]:
    cfg = read_env(ROOT / ".env", KNOWN_KEYS)
    required = KNOWN_KEYS - {"RENDER_GID"}
    if missing := required - cfg.keys():
        raise ConfigError("Faltan variables: " + ", ".join(sorted(missing)))
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", cfg["COMPOSE_PROJECT_NAME"]):
        raise ConfigError("COMPOSE_PROJECT_NAME inválido")
    for key in ("PUID", "PGID", "RENDER_GID"):
        if key in cfg and (not cfg[key].isdigit() or not 1 <= int(cfg[key]) <= 2147483647):
            raise ConfigError(f"{key} debe ser un ID numérico positivo; no uses root")
    try:
        ZoneInfo(cfg["TZ"])
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError("TZ inválida o falta tzdata") from exc
    app, data = (storage_path(cfg[k]) for k in ("APPDATA_ROOT", "DATA_ROOT"))
    if related(app, data) or related(app, ROOT) or related(data, ROOT):
        raise ConfigError("Appdata, contenido y repositorio deben estar separados")
    for key in ("HOME_WG_IP", "OVH_WG_IP"):
        private_ipv4(cfg[key])
    if cfg["HOME_WG_IP"] == cfg["OVH_WG_IP"]:
        raise ConfigError("Casa y OVH necesitan IP distintas")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,15}", cfg["WG_INTERFACE"]):
        raise ConfigError("WG_INTERFACE inválida")
    for key in ("JELLYFIN_DOMAIN", "SEERR_DOMAIN"):
        domain(cfg[key])
    if cfg["JELLYFIN_DOMAIN"] == cfg["SEERR_DOMAIN"]:
        raise ConfigError("Jellyfin y Seerr necesitan subdominios diferentes")
    for key in ("TRAEFIK_HTTP_ENTRYPOINT", "TRAEFIK_HTTPS_ENTRYPOINT", "TRAEFIK_CERT_RESOLVER"):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", cfg[key]):
            raise ConfigError(f"{key} inválido")
    if cfg["TRAEFIK_HTTP_ENTRYPOINT"] == cfg["TRAEFIK_HTTPS_ENTRYPOINT"]:
        raise ConfigError("Los entrypoints HTTP y HTTPS deben ser diferentes")
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cfg["ACME_EMAIL"]):
        raise ConfigError("ACME_EMAIL inválido")
    for name in REPOSITORIES:
        if not valid_image(cfg[f"{name}_SOURCE_IMAGE"], name, pinned=False):
            raise ConfigError(f"{name}_SOURCE_IMAGE debe usar el repositorio documentado")
    return cfg


def load_lock(target: str) -> dict[str, str]:
    lock = read_env(ROOT / "images.lock.env", LOCK_KEYS)
    names = ("TRAEFIK",) if target == "edge" else tuple(n.upper() for n in HOME_SERVICES)
    for name in names:
        if not valid_image(lock.get(f"{name}_IMAGE", ""), name, pinned=True):
            raise ConfigError(f"Falta digest válido para {name}; ejecuta ./stack lock --target {target}")
    # Validate every present item, not just the selected target.
    for key, value in lock.items():
        if not valid_image(value, key.removesuffix("_IMAGE"), pinned=True):
            raise ConfigError(f"Referencia no fijada o no admitida en {key}")
    return lock


def atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    check_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def run(argv: list[str], *, capture: bool = False, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(argv, check=True, text=True, capture_output=capture, env=env)
    except FileNotFoundError as exc:
        raise ConfigError(f"No se encuentra {argv[0]}; revisa los requisitos") from exc
    return result.stdout.strip() if capture else ""


def lock_images(cfg: dict[str, str], target: str, refresh: bool) -> None:
    path = ROOT / "images.lock.env"
    old = read_env(path, LOCK_KEYS) if path.exists() else {}
    for key, value in old.items():
        if not valid_image(value, key.removesuffix("_IMAGE"), pinned=True):
            raise ConfigError("El lock existente es inválido; revísalo antes de continuar")
    updated = dict(old)
    names = ("TRAEFIK",) if target == "edge" else tuple(s.upper() for s in HOME_SERVICES)
    for name in names:
        key = f"{name}_IMAGE"
        if key in old and not refresh:
            continue
        source = cfg[f"{name}_SOURCE_IMAGE"]
        print(f"Resolviendo {name} desde {source}…", flush=True)
        run(["docker", "pull", source])
        digests = json.loads(run(["docker", "image", "inspect", "--format",
                                  "{{json .RepoDigests}}", source], capture=True))
        if not isinstance(digests, list):
            raise ConfigError(f"Docker no devolvió una lista de digests: {name}")
        matches = [d for d in (digests or []) if isinstance(d, str) and valid_image(d, name, pinned=True)]
        if not matches:
            raise ConfigError(f"Docker no devolvió un digest del repositorio esperado: {name}")
        updated[key] = matches[0]
    if updated == old and path.exists():
        print("Lock conservado. Usa --refresh únicamente para actualizar deliberadamente.")
        return
    # Do not replace any lock until ALL selected pulls have succeeded.
    if path.exists():
        atomic_write(ROOT / "images.lock.env.previous", path.read_text())
    atomic_write(path, "# Imágenes resueltas. No editar; conservar junto con backups.\n" +
                 "".join(f"{k}={v}\n" for k, v in sorted(updated.items())))
    print("images.lock.env guardado. No se han reiniciado contenedores.")


def compose_command(cfg: dict[str, str], target: str, public: bool = False,
                    intel: bool = False) -> tuple[list[str], dict[str, str]]:
    lock = load_lock(target)
    env = dict(os.environ)
    # File values are authoritative; external shell values cannot bypass validation.
    for key in KNOWN_KEYS | LOCK_KEYS | {k for k in env if k.startswith("COMPOSE_")}:
        env.pop(key, None)
    env.update(cfg)
    env.update(lock)
    env["PROJECT_ROOT"] = str(ROOT)
    project = cfg["COMPOSE_PROJECT_NAME"] + ("-edge" if target == "edge" else "")
    cmd = ["docker", "compose", "-p", project, "--project-directory", str(ROOT), "--env-file",
           str(ROOT / ".env"), "--env-file", str(ROOT / "images.lock.env")]
    cmd += ["-f", str(ROOT / ("edge/compose.yaml" if target == "edge" else "compose.yaml"))]
    if target == "home" and public:
        cmd += ["-f", str(ROOT / "compose.public.yaml")]
    if target == "home" and intel:
        if "RENDER_GID" not in cfg:
            raise ConfigError("Configura RENDER_GID antes de usar --intel")
        cmd += ["-f", str(ROOT / "compose.intel.yaml")]
    if target == "edge" and (public or intel):
        raise ConfigError("--public y --intel solo se aplican a casa")
    return cmd, env


def ensure_dir(path: Path, uid: int, gid: int, mode: int) -> None:
    check_path(path)
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    if not path.is_dir():
        raise ConfigError(f"No es un directorio: {path}")
    if existed:
        # Avoid changing the ownership of somebody else's existing data.
        if path.stat().st_uid != uid or path.stat().st_gid != gid:
            raise ConfigError(f"Propietario distinto en {path}; revísalo manualmente. No se ha cambiado.")
        if path.stat().st_mode & 0o700 != 0o700:
            raise ConfigError(f"Faltan permisos rwx del propietario en {path}; revísalo manualmente.")
        return
    if os.geteuid() == 0:
        os.chown(path, uid, gid)
    elif uid != os.geteuid() or gid not in {os.getegid(), *os.getgroups()}:
        raise ConfigError("Ejecuta prepare con sudo o usa tus UID/GID reales")
    os.chmod(path, mode)


def prepare_home(cfg: dict[str, str]) -> None:
    app, data = Path(cfg["APPDATA_ROOT"]), Path(cfg["DATA_ROOT"])
    uid, gid = int(cfg["PUID"]), int(cfg["PGID"])
    for root in (app, data):
        check_path(root)
        root.mkdir(parents=True, exist_ok=True)
    for service in (*HOME_SERVICES, "jellyfin-cache"):
        ensure_dir(app / service, uid, gid, 0o750)
    for relative in ("torrents", "torrents/incomplete", "torrents/movies", "torrents/tv",
                     "media", "media/movies", "media/tv"):
        ensure_dir(data / relative, uid, gid, 0o2770)
    print("Directorios preparados. No se han cambiado archivos existentes recursivamente.")


def edge_config(cfg: dict[str, str]) -> str:
    for key in ("JELLYFIN_DOMAIN", "SEERR_DOMAIN"):
        domain(cfg[key], real=True)
    q = json.dumps
    lines = ["# Generado por ./stack edge-config. Solo Jellyfin y Seerr.", "http:", "  routers:"]
    for service, port in (("jellyfin", 8096), ("seerr", 5055)):
        host = cfg[f"{service.upper()}_DOMAIN"]
        lines += [f"    media-{service}-http:", f"      rule: {q(f'Host(`{host}`)')}",
                  f"      entryPoints: [{q(cfg['TRAEFIK_HTTP_ENTRYPOINT'])}]",
                  "      middlewares: [media-https]", "      service: noop@internal",
                  f"    media-{service}-https:", f"      rule: {q(f'Host(`{host}`)')}",
                  f"      entryPoints: [{q(cfg['TRAEFIK_HTTPS_ENTRYPOINT'])}]",
                  "      middlewares: [media-headers]", f"      service: media-{service}",
                  "      tls:", f"        certResolver: {q(cfg['TRAEFIK_CERT_RESOLVER'])}"]
    lines += ["  middlewares:", "    media-https:", "      redirectScheme:",
              "        scheme: https", "        permanent: true", "    media-headers:",
              "      headers:", "        contentTypeNosniff: true",
              "        referrerPolicy: strict-origin-when-cross-origin", "  services:"]
    for service, port in (("jellyfin", 8096), ("seerr", 5055)):
        upstream = f"http://{cfg['HOME_WG_IP']}:{port}"
        lines += [f"    media-{service}:", "      loadBalancer:", "        passHostHeader: true",
                  "        servers:", f"          - url: {q(upstream)}"]
    return "\n".join(lines) + "\n"


def prepare_edge() -> None:
    ensure_dir(ROOT / "edge/acme", 65532, 65532, 0o700)
    acme = ROOT / "edge/acme/acme.json"
    check_path(acme)
    if not acme.exists():
        fd = os.open(acme, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        if os.geteuid() == 0:
            os.chown(acme, 65532, 65532)
    if not acme.is_file() or acme.stat().st_uid != 65532 or acme.stat().st_gid != 65532:
        raise ConfigError("acme.json necesita propietario 65532:65532")
    if acme.stat().st_mode & 0o077:
        raise ConfigError("acme.json necesita permisos 0600")
    print("Almacenamiento ACME preparado sin reemplazar certificados.")


def public_preconditions(cfg: dict[str, str], acknowledged: bool, target: str) -> None:
    if not acknowledged:
        raise ConfigError("Completa cuentas/contraseñas y añade --accounts-configured al publicar")
    for key in ("JELLYFIN_DOMAIN", "SEERR_DOMAIN"):
        domain(cfg[key], real=True)
    if target == "home":
        addresses = json.loads(run(["ip", "-j", "address", "show", "dev", cfg["WG_INTERFACE"]], capture=True))
        if not any(a.get("local") == cfg["HOME_WG_IP"] for link in addresses for a in link.get("addr_info", [])):
            raise ConfigError("HOME_WG_IP no está asignada a la interfaz WireGuard indicada")


def check_storage(cfg: dict[str, str]) -> None:
    uid, gid = int(cfg["PUID"]), int(cfg["PGID"])
    app, data = Path(cfg["APPDATA_ROOT"]), Path(cfg["DATA_ROOT"])
    paths = [app / name for name in (*HOME_SERVICES, "jellyfin-cache")]
    paths += [data / name for name in ("media", "media/movies", "media/tv", "torrents",
                                      "torrents/movies", "torrents/tv", "torrents/incomplete")]
    for path in paths:
        check_path(path)
        if (not path.is_dir() or path.stat().st_uid != uid or path.stat().st_gid != gid
                or path.stat().st_mode & 0o700 != 0o700):
            raise ConfigError(f"Directorio ausente o propietario incorrecto: {path}; revisa prepare")


def backup_home(cfg: dict[str, str], output: Path) -> None:
    if (not output.is_absolute() or ".." in output.parts
            or output.suffixes[-2:] != [".tar", ".gz"]):
        raise ConfigError("Backup: usa una ruta absoluta acabada en .tar.gz")
    check_path(output)
    if output.exists():
        raise ConfigError("El backup de destino ya existe; no se sobrescribe")
    if any(related(output, p) for p in (Path(cfg["APPDATA_ROOT"]), Path(cfg["DATA_ROOT"]), ROOT)):
        raise ConfigError("Guarda el backup fuera del repositorio y de los datos")
    check_storage(cfg)
    cmd, env = compose_command(cfg, "home")
    running = run(cmd + ["ps", "--status", "running", "--services"], capture=True, env=env).splitlines()
    if any(service not in HOME_SERVICES for service in running):
        raise ConfigError("El proyecto contiene servicios inesperados")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".media-backup-", dir=output.parent)
    os.close(fd)
    try:
        try:
            if running:
                run(cmd + ["stop", *running], env=env)
            with tarfile.open(temporary, "w:gz", dereference=False) as archive:
                for service in HOME_SERVICES:
                    archive.add(Path(cfg["APPDATA_ROOT"]) / service, arcname=f"appdata/{service}")
                for filename in (".env", "images.lock.env"):
                    archive.add(ROOT / filename, arcname=filename)
            os.chmod(temporary, 0o600)
            # Atomic no-clobber publication; destination is on the same filesystem.
            os.link(temporary, output)
        finally:
            if running:
                run(cmd + ["start", *running], env=env)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print("Backup de configuración creado; películas, descargas y caché no están incluidos.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Docker media stack para Debian + entrada OVH")
    parser.add_argument("action", choices=("init", "check", "prepare", "prepare-edge", "lock",
                                          "config", "up", "down", "status", "logs", "edge-config", "backup"))
    parser.add_argument("--target", choices=("home", "edge"), default="home")
    parser.add_argument("--public", action="store_true", help="Añadir acceso por WireGuard en casa")
    parser.add_argument("--intel", action="store_true", help="Añadir renderD128 Intel/AMD verificado")
    parser.add_argument("--accounts-configured", action="store_true", help="Confirma que has terminado el bootstrap privado")
    parser.add_argument("--refresh", action="store_true", help="Resolver deliberadamente nuevas imágenes")
    parser.add_argument("--service", choices=(*HOME_SERVICES, "traefik"))
    parser.add_argument("--output", type=Path, help="Destino absoluto .tar.gz para backup")
    args = parser.parse_args(argv)
    try:
        if args.action == "init":
            path = ROOT / ".env"
            check_path(path)
            # O_EXCL avoids replacing an existing configuration, including concurrent init.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write((ROOT / ".env.example").read_text())
            print(".env creado. Ajusta UID/GID, rutas, dominios e IP del túnel.")
            return 0
        cfg = load_config()
        if args.action == "check":
            print("Configuración válida. Las cuentas y el túnel todavía requieren comprobación real.")
        elif args.action == "prepare":
            prepare_home(cfg)
        elif args.action == "prepare-edge":
            prepare_edge()
        elif args.action == "lock":
            lock_images(cfg, args.target, args.refresh)
        elif args.action == "edge-config":
            public_preconditions(cfg, args.accounts_configured, "edge")
            atomic_write(ROOT / "edge/dynamic/media.yml", edge_config(cfg), mode=0o644)
            print("edge/dynamic/media.yml generado. Copia el archivo al proveedor file de OVH.")
        elif args.action == "backup":
            if args.target != "home" or args.output is None:
                raise ConfigError("Backup: solo casa, con --output /ruta/copia.tar.gz")
            backup_home(cfg, args.output)
        else:
            cmd, env = compose_command(cfg, args.target, args.public, args.intel)
            if args.action == "up":
                if args.public or args.target == "edge":
                    public_preconditions(cfg, args.accounts_configured, args.target)
                if args.target == "home":
                    check_storage(cfg)
                    if args.intel and not Path("/dev/dri/renderD128").exists():
                        raise ConfigError("No existe /dev/dri/renderD128")
                else:
                    if any(cfg[k] != v for k, v in {
                        "TRAEFIK_HTTP_ENTRYPOINT": "web", "TRAEFIK_HTTPS_ENTRYPOINT": "websecure",
                        "TRAEFIK_CERT_RESOLVER": "letsencrypt"}.items()):
                        raise ConfigError("El Traefik incluido usa web/websecure/letsencrypt")
                    if cfg["ACME_EMAIL"].endswith("@example.com"):
                        raise ConfigError("Configura un correo real para ACME")
                    config_file = ROOT / "edge/dynamic/media.yml"
                    check_path(config_file)
                    if not config_file.is_file() or config_file.read_text() != edge_config(cfg):
                        raise ConfigError("Genera de nuevo edge-config antes de arrancar OVH")
                    acme = ROOT / "edge/acme/acme.json"
                    check_path(acme)
                    if not acme.is_file() or acme.stat().st_uid != 65532 or acme.stat().st_mode & 0o077:
                        raise ConfigError("Prepara ACME con sudo ./stack prepare-edge")
                run(cmd + ["config", "--quiet"], env=env)
                run(cmd + ["up", "-d", "--wait", "--wait-timeout", "240"], env=env)
            elif args.action == "config":
                run(cmd + ["config", "--quiet"], env=env)
                print("Docker Compose acepta la configuración seleccionada.")
            elif args.action == "status":
                run(cmd + ["ps"], env=env)
            elif args.action == "logs":
                allowed = ("traefik",) if args.target == "edge" else HOME_SERVICES
                if args.service not in allowed:
                    raise ConfigError("Indica --service del entorno seleccionado")
                run(cmd + ["logs", "--tail", "100", args.service], env=env)
            elif args.action == "down":
                run(cmd + ["down"], env=env)
        return 0
    except (ConfigError, OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        # Avoid replaying captured Docker output/credentials in failure messages.
        if isinstance(exc, subprocess.CalledProcessError):
            print("Error en Docker/ip. Revisa el estado del servicio y la conectividad.", file=sys.stderr)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
