#!/usr/bin/env python3
"""Offline deployment contracts; NOT a substitute for docker compose config."""
import importlib.util
from pathlib import Path
import re
import sys

try:
    import yaml
except ImportError:
    raise SystemExit("Instala python3-yaml para esta comprobación opcional")

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stack_check", ROOT / "scripts/stack.py")
stack = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = stack
spec.loader.exec_module(stack)

cfg = stack.read_env(ROOT / ".env.example", stack.KNOWN_KEYS)
cfg.update({f"{name}_IMAGE": f"{repo}@sha256:{'a'*64}" for name, repo in stack.REPOSITORIES.items()})
cfg.update(PROJECT_ROOT=str(ROOT), RENDER_GID="109", JELLYFIN_DOMAIN="cine.srpolvoron.test",
           SEERR_DOMAIN="peticiones.srpolvoron.test")


def load(filename):
    text = (ROOT / filename).read_text()
    # These files intentionally use only ${NAME:?message}, no shell expressions.
    text = re.sub(r"\$\{([A-Z_]+)(?::\?[^}]*)?\}", lambda m: cfg[m[1]], text)
    assert "${" not in text, f"Unresolved interpolation in {filename}"
    return yaml.safe_load(text)


def check():
    base = load("compose.yaml")
    assert set(base["services"]) == set(stack.HOME_SERVICES)
    fields = {"restart", "user", "cap_drop", "security_opt", "stop_grace_period", "logging",
              "environment", "tmpfs", "image", "init", "ports", "volumes", "networks",
              "mem_limit", "healthcheck"}
    for name, service in base["services"].items():
        assert not set(service) - fields, f"Unexpected fields for {name}"
        assert service["cap_drop"] == ["ALL"]
        assert service["user"] == "1000:1000"
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert "@sha256:" in service["image"]
        assert all(port.startswith("127.0.0.1:") for port in service["ports"])
        assert set(service["networks"]) <= {"playback", "automation", "downloads"}
        for volume in service["volumes"]:
            assert volume["type"] == "bind"
            assert volume["bind"]["create_host_path"] is False
            assert "/var/run/docker.sock" not in volume["source"]
        assert service["logging"]["options"]["max-size"] == "10m"

    jellyfin = base["services"]["jellyfin"]
    media = next(v for v in jellyfin["volumes"] if v["target"] == "/media")
    assert media["read_only"] is True
    assert media["source"] == cfg["DATA_ROOT"] + "/media"
    for name in ("radarr", "sonarr"):
        assert any(v["target"] == "/data" and v["source"] == cfg["DATA_ROOT"]
                   for v in base["services"][name]["volumes"])
        assert set(base["services"][name]["networks"]) == {"automation", "downloads"}
    assert base["networks"]["downloads"] == {
        "external": True,
        "name": cfg["SHARED_NETWORK"],
    }
    bazarr = base["services"]["bazarr"]
    assert bazarr["ports"] == ["127.0.0.1:6767:6767"]
    assert any(v["target"] == "/data/media" and v["source"] == cfg["DATA_ROOT"] + "/media"
               for v in bazarr["volumes"])
    assert not any(v["target"] == "/data/torrents" for v in bazarr["volumes"])
    assert "qbittorrent" not in base["services"]
    for name in ("radarr", "sonarr", "prowlarr", "bazarr"):
        assert any(v.startswith("/run:uid=1000,gid=1000,") and ",exec," in v
                   for v in base["services"][name]["tmpfs"])

    public = load("compose.public.yaml")
    assert set(public["services"]) == {"jellyfin", "seerr"}
    for name, service in public["services"].items():
        assert set(service) == {"ports"}
        assert all(p.startswith("10.77.0.2:") for p in service["ports"])
        # Compose uses (IP,target,published,protocol) as port uniqueness key.
        combined = base["services"][name]["ports"] + service["ports"]
        assert len(combined) == len(set(combined)) == 2

    admin = load("compose.override.yaml")
    admin_ports = {
        "radarr": 7878,
        "sonarr": 8989,
        "prowlarr": 9696,
        "bazarr": 6767,
    }
    assert set(admin["services"]) == set(admin_ports)
    for name, port in admin_ports.items():
        service = admin["services"][name]
        assert set(service) == {"ports"}
        assert service["ports"] == [f"10.77.0.2:{port}:{port}"]
        combined = base["services"][name]["ports"] + service["ports"]
        assert len(combined) == len(set(combined)) == 2

    intel = load("compose.intel.yaml")
    assert set(intel["services"]) == {"jellyfin"}
    assert intel["services"]["jellyfin"]["group_add"] == ["109"]

    edge = load("edge/compose.yaml")["services"]["traefik"]
    assert edge["ports"] == ["80:80", "443:443"]
    assert edge["user"] == "65532:65532"
    assert edge["read_only"] is True
    assert edge["cap_drop"] == ["ALL"] and edge["cap_add"] == ["NET_BIND_SERVICE"]
    assert not any("docker.sock" in v["source"] for v in edge["volumes"])
    assert "--api.dashboard=false" in edge["command"]
    assert "--providers.file.directory=/etc/traefik/dynamic" in edge["command"]

    proxy = yaml.safe_load(stack.edge_config(cfg))["http"]
    assert set(proxy["services"]) == {"media-jellyfin", "media-seerr"}
    assert len(proxy["routers"]) == 4
    for name, port in (("jellyfin", 8096), ("seerr", 5055)):
        https = proxy["routers"][f"media-{name}-https"]
        assert https["tls"]["certResolver"] == "letsencrypt"
        assert https["entryPoints"] == ["websecure"]
        assert https["rule"] == f"Host(`{cfg[name.upper() + '_DOMAIN']}`)"
        assert proxy["services"][f"media-{name}"]["loadBalancer"]["servers"] == [
            {"url": f"http://10.77.0.2:{port}"}]
    assert proxy["middlewares"]["media-https"]["redirectScheme"]["scheme"] == "https"
    for filename in ("home", "ovh"):
        text = (ROOT / f"examples/wireguard/{filename}.conf.example").read_text()
        allowed = re.findall(r"^AllowedIPs = (.+)$", text, flags=re.M)
        assert len(allowed) == 1 and allowed[0].endswith("/32")
        assert "0.0.0.0/0" not in text
    print("OK: YAML, aislamiento, permisos, almacenamiento, overlays, proxy y rutas WireGuard.")
    print("Falta ejecutar docker compose config y las pruebas reales en Debian/OVH.")


if __name__ == "__main__":
    check()
