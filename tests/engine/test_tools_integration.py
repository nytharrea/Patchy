import json
import os
import stat
import sys
from pathlib import Path

import pytest

from patchy.engine import patcher, signer

FINGERPRINT = "ab" * 32

FAKE_APKSIGNER = """#!{python}
import os
import shutil
import sys

args = sys.argv[1:]
if args[0] == "sign":
    out = args[args.index("--out") + 1]
    ks_ref = args[args.index("--ks-pass") + 1]
    key_ref = args[args.index("--key-pass") + 1]
    assert ks_ref.startswith("env:") and key_ref.startswith("env:")
    assert "GITHUB_TOKEN" not in os.environ
    shutil.copyfile(args[-1], out)
    with open(out, "ab") as f:
        f.write(("|" + os.environ[ks_ref[4:]] + ":" + os.environ[key_ref[4:]]).encode())
elif args[0] == "verify":
    print("Signer #1 certificate SHA-256 digest: {fingerprint}")
else:
    sys.exit(2)
"""

FAKE_ZIPALIGN = """#!{python}
import shutil
import sys

shutil.copyfile(sys.argv[-2], sys.argv[-1])
with open(sys.argv[-1], "ab") as f:
    f.write(b"|aligned")
"""

FAILING_APKSIGNER = """#!{python}
import sys

print("Failed to load signer: bad alias")
sys.exit(1)
"""

FAKE_JAVA = """#!{python}
import json
import os
import sys
import time

apk = sys.argv[-1]
mode = os.path.exists(apk + ".hang")
with open(apk + ".env", "w") as f:
    json.dump(sorted(os.environ), f)
if mode:
    print("INFO: starting", flush=True)
    time.sleep(30)
out = apk + "-patched.apk"
with open(out, "wb") as f:
    f.write(b"patched")
print("INFO: Applying 3 patches")
print("x" * 200000)
print("INFO: Saved to " + out)
"""


def _script(path: Path, template: str) -> Path:
    path.write_text(template.replace("{python}", sys.executable).replace("{fingerprint}", FINGERPRINT))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _creds(tmp_path):
    keystore = tmp_path / "release.keystore"
    keystore.write_bytes(b"fake keystore")
    return signer.Credentials(keystore, "release-key", "storepass123", "keypass456")


async def test_sign_apk_runs_the_real_tool_chain_with_passwords_only_in_its_environment(monkeypatch, tmp_path):
    apksigner = _script(tmp_path / "apksigner", FAKE_APKSIGNER)
    zipalign = _script(tmp_path / "zipalign", FAKE_ZIPALIGN)
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_secret")
    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin"))
    monkeypatch.setattr(signer.settings, "apksigner", apksigner)
    monkeypatch.setattr(signer.settings, "zipalign", zipalign)
    monkeypatch.setattr(signer.settings, "tool_timeout", 30.0)
    monkeypatch.setattr(signer.log, "warn", lambda msg: None)
    source = tmp_path / "YouTube-1.0.apk"
    source.write_bytes(b"patched")
    dest = tmp_path / "signed" / "YouTube-1.0.apk"

    fingerprint = await signer.sign_apk(source, dest, _creds(tmp_path))

    assert fingerprint == FINGERPRINT
    assert dest.read_bytes() == b"patched|aligned|storepass123:keypass456"
    assert [p.name for p in dest.parent.iterdir()] == ["YouTube-1.0.apk"]


async def test_sign_apk_reports_a_failing_tool_with_its_output(monkeypatch, tmp_path):
    failing = _script(tmp_path / "apksigner", FAILING_APKSIGNER)
    zipalign = _script(tmp_path / "zipalign", FAKE_ZIPALIGN)
    monkeypatch.setattr(signer.settings, "apksigner", failing)
    monkeypatch.setattr(signer.settings, "zipalign", zipalign)
    monkeypatch.setattr(signer.settings, "tool_timeout", 30.0)
    source = tmp_path / "YouTube-1.0.apk"
    source.write_bytes(b"patched")

    with pytest.raises(signer.SigningError, match="bad alias"):
        await signer.sign_apk(source, tmp_path / "signed" / "YouTube-1.0.apk", _creds(tmp_path))


def _fake_java(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _script(bin_dir / "java", FAKE_JAVA)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '/usr/bin')}")
    monkeypatch.setattr(patcher.log, "patch_line", lambda line: None)
    monkeypatch.setattr(patcher.log, "notice", lambda msg: None)


async def test_patch_apk_streams_a_real_process_including_very_long_lines(monkeypatch, tmp_path):
    _fake_java(monkeypatch, tmp_path)
    monkeypatch.setattr(patcher.settings, "patch_timeout", 30.0)
    apk = tmp_path / "in.apk"
    apk.write_bytes(b"original")

    result = await patcher.patch_apk("cli.jar", ["a.mpp"], str(apk))

    assert result == str(apk) + "-patched.apk"
    assert Path(result).read_bytes() == b"patched"


async def test_patch_apk_starts_the_real_process_without_any_secrets(monkeypatch, tmp_path):
    _fake_java(monkeypatch, tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_secret")
    monkeypatch.setenv("KS_PASSWORD", "storepass123")
    monkeypatch.setenv("JAVA_HOME", "/opt/java")
    monkeypatch.setattr(patcher.settings, "patch_timeout", 30.0)
    apk = tmp_path / "in.apk"
    apk.write_bytes(b"original")

    await patcher.patch_apk("cli.jar", ["a.mpp"], str(apk))

    seen = json.loads(Path(str(apk) + ".env").read_text())
    assert "PATH" in seen and "JAVA_HOME" in seen
    assert "GITHUB_TOKEN" not in seen and "KS_PASSWORD" not in seen


async def test_patch_apk_kills_a_real_process_that_goes_silent(monkeypatch, tmp_path):
    _fake_java(monkeypatch, tmp_path)
    monkeypatch.setattr(patcher.settings, "patch_timeout", 0.5)
    apk = tmp_path / "in.apk"
    apk.write_bytes(b"original")
    Path(str(apk) + ".hang").write_text("")

    with pytest.raises(patcher.PatchTimeout, match="timed out"):
        await patcher.patch_apk("cli.jar", ["a.mpp"], str(apk))
