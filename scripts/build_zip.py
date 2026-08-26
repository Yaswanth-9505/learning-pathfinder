"""Package the source for submission.

Excludes dependency folders, build artifacts, the local database and the real
.env (which holds a live API key). Ships .env.example instead.
"""

import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "learning-pathfinder-source.zip"

EXCLUDE_DIRS = {
    "node_modules", "dist", "build", "__pycache__", ".pytest_cache",
    "venv", ".venv", ".git", ".vite", ".idea", ".vscode",
}
EXCLUDE_FILES = {
    ".env", ".DS_Store", "pathfinder.db", OUT.name,
}


def main():
    if OUT.exists():
        OUT.unlink()

    added = []
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for name in filenames:
                if name in EXCLUDE_FILES or name.endswith((".pyc", ".zip")):
                    continue
                full = Path(dirpath) / name
                rel = full.relative_to(ROOT)
                archive.write(full, Path("learning-pathfinder") / rel)
                added.append(rel.as_posix())

    for path in sorted(added):
        print("  " + path)
    print("\n%d files, %.1f KB" % (len(added), OUT.stat().st_size / 1024))
    print("written to %s" % OUT.name)


if __name__ == "__main__":
    main()
