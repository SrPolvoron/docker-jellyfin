"""Regression tests for configuration, publication and data protection boundaries."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stack_tools", PROJECT / "scripts/stack.py")
stack = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = stack
spec.loader.exec_module(stack)


class StackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(stack, "ROOT", self.root).start()
        text = (PROJECT / ".env.example").read_text()
        text = text.replace("/srv/jellyfin-home/appdata", str(self.base / "appdata"))
        text = text.replace("/srv/media", str(self.base / "media"))
        (self.root / ".env.example").write_text(text)
        (self.root / ".env").write_text(text)

    def change(self, key, value):
        file = self.root / ".env"
        lines = file.read_text().splitlines()
        for i, line in enumerate(lines):
            if line.startswith(key + "="):
                lines[i] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
        file.write_text("\n".join(lines) + "\n")

    def real_config(self):
        self.change("JELLYFIN_DOMAIN", "cine.srpolvoron.test")
        self.change("SEERR_DOMAIN", "peticiones.srpolvoron.test")
        return stack.load_config()

    def locks(self):
        values = {f"{name}_IMAGE": f"{repo}@sha256:{'a' * 64}"
                  for name, repo in stack.REPOSITORIES.items()}
        (self.root / "images.lock.env").write_text("".join(f"{k}={v}\n" for k, v in values.items()))
        return values

    def test_example_works_for_private_bootstrap(self):
        self.assertEqual(stack.load_config()["HOME_WG_IP"], "10.77.0.2")

    def test_shell_substitution_is_never_executed(self):
        self.change("TZ", "$(touch /tmp/unwanted)")
        with patch.object(stack, "run") as run, self.assertRaises(stack.ConfigError):
            stack.load_config()
        run.assert_not_called()

    def test_duplicate_key_rejected(self):
        with (self.root / ".env").open("a") as stream:
            stream.write("PUID=2000\n")
        with self.assertRaises(stack.ConfigError):
            stack.load_config()

    def test_unknown_key_rejected(self):
        self.change("EVIL", "x")
        with self.assertRaises(stack.ConfigError):
            stack.load_config()

    def test_root_and_non_numeric_ids_rejected(self):
        for value in ("0", "-1", "abc", "2147483648"):
            with self.subTest(value=value):
                self.change("PUID", value)
                with self.assertRaises(stack.ConfigError):
                    stack.load_config()

    def test_wildcard_public_and_loopback_tunnel_ips_rejected(self):
        for value in ("0.0.0.0", "127.0.0.1", "8.8.8.8", "100.64.0.1", "::"):
            with self.subTest(value=value):
                self.change("HOME_WG_IP", value)
                with self.assertRaises(stack.ConfigError):
                    stack.load_config()

    def test_domain_cannot_inject_a_traefik_rule(self):
        self.change("JELLYFIN_DOMAIN", "evil.test`)||Host(`other.test")
        with self.assertRaises(stack.ConfigError):
            stack.load_config()

    def test_domain_collision_rejected(self):
        self.change("SEERR_DOMAIN", "cine.example.com")
        with self.assertRaises(stack.ConfigError):
            stack.load_config()

    def test_critical_system_path_rejected(self):
        self.change("DATA_ROOT", "/etc/media")
        with self.assertRaises(stack.ConfigError):
            stack.load_config()

    def test_overlapping_appdata_and_media_rejected(self):
        self.change("DATA_ROOT", str(self.base / "appdata/media"))
        with self.assertRaises(stack.ConfigError):
            stack.load_config()

    def test_symlinked_storage_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.base / "alias").symlink_to(outside, target_is_directory=True)
        self.change("DATA_ROOT", str(self.base / "alias/media"))
        with self.assertRaises(stack.ConfigError):
            stack.load_config()
        self.assertEqual(list(outside.iterdir()), [])

    def test_publication_needs_completed_bootstrap_declaration(self):
        with patch.object(stack, "run") as run, self.assertRaises(stack.ConfigError):
            stack.public_preconditions(self.real_config(), False, "home")
        run.assert_not_called()

    def test_publication_rejects_example_domains(self):
        with self.assertRaises(stack.ConfigError):
            stack.public_preconditions(stack.load_config(), True, "edge")

    def test_publication_requires_address_on_selected_interface(self):
        cfg = self.real_config()
        with patch.object(stack, "run", return_value='[{"addr_info": []}]'), self.assertRaises(stack.ConfigError):
            stack.public_preconditions(cfg, True, "home")
        with patch.object(stack, "run", return_value='[{"addr_info": [{"local": "10.77.0.2"}]}]') as run:
            stack.public_preconditions(cfg, True, "home")
        self.assertEqual(run.call_args.args[0][-1], "wg-media")

    def test_floating_or_other_repository_lock_rejected(self):
        self.locks()
        file = self.root / "images.lock.env"
        for value in ("jellyfin/jellyfin:latest", f"evil/jellyfin@sha256:{'a'*64}"):
            with self.subTest(value=value):
                file.write_text("JELLYFIN_IMAGE=" + value + "\n")
                with self.assertRaises(stack.ConfigError):
                    stack.load_lock("home")

    def test_partial_pull_failure_keeps_old_lock(self):
        self.locks()
        before = (self.root / "images.lock.env").read_bytes()
        calls = 0

        def fail_later(argv, **kwargs):
            nonlocal calls
            if argv[1] == "pull":
                calls += 1
                if calls == 2:
                    raise subprocess.CalledProcessError(1, argv)
                return ""
            return '["jellyfin/jellyfin@sha256:' + 'b'*64 + '"]'

        with patch.object(stack, "run", side_effect=fail_later), self.assertRaises(subprocess.CalledProcessError):
            stack.lock_images(stack.load_config(), "home", True)
        self.assertEqual((self.root / "images.lock.env").read_bytes(), before)
        self.assertFalse((self.root / "images.lock.env.previous").exists())

    def test_lock_is_not_refreshed_implicitly(self):
        self.locks()
        with patch.object(stack, "run") as run:
            stack.lock_images(stack.load_config(), "home", False)
        run.assert_not_called()

    def test_host_and_edge_project_names_do_not_collide(self):
        self.locks()
        cfg = stack.load_config()
        home, _ = stack.compose_command(cfg, "home")
        edge, _ = stack.compose_command(cfg, "edge")
        self.assertEqual(home[home.index("-p") + 1], "srpolvoron-media")
        self.assertEqual(edge[edge.index("-p") + 1], "srpolvoron-media-edge")

    def test_shell_environment_cannot_override_binding_or_digest(self):
        locks = self.locks()
        with patch.dict(os.environ, {"HOME_WG_IP": "0.0.0.0", "JELLYFIN_IMAGE": "evil:latest",
                                     "COMPOSE_FILE": "/tmp/evil.yaml"}):
            _, env = stack.compose_command(stack.load_config(), "home", True)
        self.assertEqual(env["HOME_WG_IP"], "10.77.0.2")
        self.assertEqual(env["JELLYFIN_IMAGE"], locks["JELLYFIN_IMAGE"])
        self.assertNotIn("COMPOSE_FILE", env)

    def test_atomic_write_does_not_follow_symlink(self):
        victim = self.base / "victim"
        victim.write_text("keep")
        link = self.root / "generated"
        link.symlink_to(victim)
        with self.assertRaises(stack.ConfigError):
            stack.atomic_write(link, "changed")
        self.assertEqual(victim.read_text(), "keep")

    def test_prepare_does_not_take_over_existing_directory(self):
        path = self.base / "owned"
        path.mkdir()
        before = path.stat()
        other_uid = before.st_uid + 1
        with patch.object(os, "chown") as chown, self.assertRaises(stack.ConfigError):
            stack.ensure_dir(path, other_uid, before.st_gid, 0o750)
        chown.assert_not_called()
        self.assertEqual(path.stat().st_uid, before.st_uid)

    def test_init_never_overwrites_existing_env(self):
        before = (self.root / ".env").read_bytes()
        self.assertEqual(stack.main(["init"]), 1)
        self.assertEqual((self.root / ".env").read_bytes(), before)

    def test_backup_rejects_destination_in_data_before_docker(self):
        cfg = stack.load_config()
        with patch.object(stack, "run") as run, self.assertRaises(stack.ConfigError):
            stack.backup_home(cfg, self.base / "media/backup.tar.gz")
        run.assert_not_called()

    def test_backup_parent_traversal_is_rejected(self):
        cfg = stack.load_config()
        output = self.base / "other/../appdata/jellyfin/copy.tar.gz"
        with patch.object(stack, "run") as run, self.assertRaises(stack.ConfigError):
            stack.backup_home(cfg, output)
        run.assert_not_called()

    def test_backup_preserves_stopped_services_and_excludes_media_cache(self):
        self.locks()
        cfg = stack.load_config()
        app = Path(cfg["APPDATA_ROOT"])
        for service in stack.HOME_SERVICES:
            (app / service).mkdir(parents=True)
            (app / service / "config.json").write_text(service)
        (app / "jellyfin-cache").mkdir()
        (app / "jellyfin-cache/private.cache").write_text("excluded")
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return "jellyfin\nseerr" if "ps" in argv else ""

        output = self.base / "backups/config.tar.gz"
        with patch.object(stack, "check_storage"), patch.object(stack, "run", side_effect=runner):
            stack.backup_home(cfg, output)
        self.assertEqual(calls[-1][-3:], ["start", "jellyfin", "seerr"])
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        with tarfile.open(output) as archive:
            names = archive.getnames()
            self.assertIn("appdata/qbittorrent/config.json", names)
            self.assertIn(".env", names)
            self.assertIn("images.lock.env", names)
            self.assertFalse(any("cache" in name or "torrents" in name for name in names))

    def test_backup_partial_stop_failure_attempts_restart(self):
        self.locks()
        calls = []

        def partial_failure(argv, **kwargs):
            calls.append(argv)
            if "ps" in argv:
                return "jellyfin\nradarr"
            if "stop" in argv:
                raise subprocess.CalledProcessError(1, argv)
            return ""

        with patch.object(stack, "check_storage"), patch.object(stack, "run", side_effect=partial_failure):
            with self.assertRaises(subprocess.CalledProcessError):
                stack.backup_home(stack.load_config(), self.base / "backups/config.tar.gz")
        self.assertEqual(calls[-1][-3:], ["start", "jellyfin", "radarr"])
        self.assertFalse((self.base / "backups/config.tar.gz").exists())
        self.assertEqual(list((self.base / "backups").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
