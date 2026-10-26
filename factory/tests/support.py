"""Shared helpers: load factory/bin scripts as modules and build throwaway git repos."""

import importlib.machinery
import importlib.util
import subprocess
import tempfile
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"


def load_script(name):
    loader = importlib.machinery.SourceFileLoader(f"factory_{name}", str(BIN / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(cwd), "PATH": "/usr/bin:/bin:/usr/local/bin"}).stdout


def make_repo(files):
    """A repo whose `origin/main` ref points at a first commit holding <files>; HEAD is the same commit."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    git(root, "init", "-q", "-b", "main")
    write(root, files)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return tmp, root


def write(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def commit(root, files, message="change"):
    write(root, files)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD").strip()
