"""Pruebas de fallos del script, sin Docker, redes, repositorios ni secretos reales.

python -m unittest discover -s infra/tests -v
En Windows usa Git Bash; flock se simula (su exclusión mutua se valida en Linux).
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SHELL = shutil.which("sh") if os.name != "nt" else "C:/Program Files/Git/bin/bash.exe"


def shell_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if os.name == "nt":
        return "/" + value[0].lower() + value[2:]
    return value


@unittest.skipUnless(SHELL and Path(SHELL).is_file(), "Requiere sh o Git Bash")
class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="uno-backup-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.runtime = self.root / "runtime.env"
        self.runtime.write_text("POSTGRES_PASSWORD=fake-test-only\n", encoding="utf-8")
        self.password = self.root / "password"
        self.password.write_text("fake-test-only\n", encoding="utf-8")
        self.log = self.root / "commands.log"
        self.script("flock", "exit 0\n")
        self.script("docker", '''
printf 'docker %s\\n' "$*" >> "$TEST_LOG"
case "$*" in
  *pg_dump*)
    [ "$TEST_FAILURE" = empty ] || printf 'fake postgres custom archive\\n'
    [ "$TEST_FAILURE" != dump ] || exit 7
    ;;
  *pg_restore*)
    cat >/dev/null
    [ "$TEST_FAILURE" != verify ] || exit 8
    ;;
  *) exit 99 ;;
esac
''')
        self.script("restic", '''
printf 'restic %s\\n' "$*" >> "$TEST_LOG"
[ "$TEST_FAILURE" != "$1" ] || exit 9
''')
        self.env = {
            **os.environ,
            "PATH": shell_path(self.bin) + ":/usr/bin:/bin",
            "UNO_BACKUP_ENV_FILE": shell_path(self.root / "absent.env"),
            "UNO_BACKUP_APP_DIR": shell_path(ROOT),
            "UNO_BACKUP_DIR": shell_path(self.backups),
            "UNO_RUNTIME_ENV_FILE": shell_path(self.runtime),
            "UNO_BACKUP_COMPOSE_FILE": shell_path(ROOT / "infra/docker-compose.prod.yml"),
            "UNO_BACKUP_OFFSITE": "1",
            "UNO_BACKUP_LOCAL_DAYS": "7",
            "RESTIC_REPOSITORY": "s3:https://storage.invalid/test-only/uno",
            "RESTIC_PASSWORD_FILE": shell_path(self.password),
            "RESTIC_CACHE_DIR": shell_path(self.root / "cache"),
            "TEST_LOG": shell_path(self.log),
            "TEST_FAILURE": "none",
        }

    def script(self, name: str, text: str) -> None:
        path = self.bin / name
        path.write_text("#!/bin/sh\nset -eu\n" + text, encoding="utf-8", newline="\n")
        path.chmod(0o700)

    def run_backup(self, failure: str = "none") -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(SHELL), shell_path(ROOT / "infra/backup.sh")],
            env={**self.env, "TEST_FAILURE": failure},
            text=True, capture_output=True, timeout=20,
        )

    def old_dump(self) -> Path:
        old = self.backups / "uno-old.dump"
        old.write_text("keep until upload succeeds", encoding="utf-8")
        os.utime(old, (time.time() - 30 * 86400,) * 2)
        return old

    def test_success_uploads_secrets_encrypted_and_applies_scoped_retention(self) -> None:
        old = self.old_dump()
        result = self.run_backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(old.exists())
        self.assertEqual(len(list(self.backups.glob("uno-*.dump"))), 1)
        self.assertFalse(list(self.backups.glob("*.partial")))
        self.assertTrue((self.backups / "last-offsite-success").exists())
        log = self.log.read_text(encoding="utf-8")
        self.assertIn(shell_path(self.runtime), log)
        self.assertIn("pg_restore --file=/dev/null", log)
        self.assertIn("--tag uno-visitas --group-by host,tags --keep-last 1", log)
        self.assertLess(log.index("restic backup"), log.index("restic check"))
        self.assertLess(log.index("restic check"), log.index("restic forget"))

    def test_dump_or_validation_failure_never_promotes_partial(self) -> None:
        for stage in ("dump", "empty", "verify"):
            with self.subTest(stage=stage):
                result = self.run_backup(stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(list(self.backups.glob("uno-*.dump")))
                self.assertTrue(list(self.backups.glob("*.partial")))
                self.assertNotIn("restic backup", self.log.read_text())

    def test_offsite_failure_keeps_all_local_dumps_and_no_success_marker(self) -> None:
        old = self.old_dump()
        for stage in ("backup", "check", "forget"):
            with self.subTest(stage=stage):
                result = self.run_backup(stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(old.exists())
                self.assertGreater(len(list(self.backups.glob("uno-*.dump"))), 1)
                self.assertFalse((self.backups / "last-offsite-success").exists())

    def test_local_mode_explicitly_reports_no_offsite_protection(self) -> None:
        self.env["UNO_BACKUP_OFFSITE"] = "0"
        result = self.run_backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Solo respaldo local", result.stdout)
        self.assertNotIn("restic", self.log.read_text())
        self.assertFalse((self.backups / "last-offsite-success").exists())

    def test_local_repository_is_refused_without_deleting_dump(self) -> None:
        self.env["RESTIC_REPOSITORY"] = shell_path(self.root / "local-repo")
        result = self.run_backup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(list(self.backups.glob("uno-*.dump"))), 1)
        self.assertNotIn("restic", self.log.read_text())


if __name__ == "__main__":
    unittest.main()
