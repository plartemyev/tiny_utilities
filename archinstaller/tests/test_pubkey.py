import pytest

from archinstaller.pubkey import resolve_public_key

KEY = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDU0ZDDGMlGKUYbFQtKyODXXUequNtcQz+2UVe5Vr9A0"
       " pasha@p-745-g5")


def test_accepts_key_string():
    assert resolve_public_key(KEY) == KEY


def test_normalizes_whitespace():
    assert resolve_public_key("  " + KEY.replace(" ", "   ") + "\n") == KEY


def test_accepts_file_path(tmp_path):
    key_file = tmp_path / "id_ed25519.pub"
    key_file.write_text("# my key\n\n" + KEY + "\n")
    assert resolve_public_key(str(key_file)) == KEY


def test_accepts_tilde_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "key.pub").write_text(KEY + "\n")
    assert resolve_public_key("~/key.pub") == KEY


def test_rejects_garbage():
    with pytest.raises(ValueError):
        resolve_public_key("hello world")


def test_rejects_missing_file():
    with pytest.raises(ValueError):
        resolve_public_key("/nonexistent/key.pub")


def test_rejects_bad_base64():
    with pytest.raises(ValueError):
        resolve_public_key("ssh-ed25519 not-base64!!")


def test_rejects_unknown_key_type():
    with pytest.raises(ValueError):
        resolve_public_key("unknown-type AAAAB3NzaC1yc2E")


def test_rejects_file_without_valid_key(tmp_path):
    key_file = tmp_path / "notes.txt"
    key_file.write_text("nothing here\n")
    with pytest.raises(ValueError):
        resolve_public_key(str(key_file))
