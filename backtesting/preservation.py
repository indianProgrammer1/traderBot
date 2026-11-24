"""Verify the original source/build files without writing to the production tree."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent


def git(*args):
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return {"exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def verify():
    baseline = json.loads((BASE / "preservation_before.json").read_text())
    differences = []
    for name, hashes in baseline["files"].items():
        path = ROOT / name
        if not path.is_file():
            differences.append({"file": name, "problem": "missing"})
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        blob_result = git("hash-object", "--no-filters", str(path))
        blob = blob_result["stdout"].strip()
        if sha != hashes["sha256"] or blob != hashes["git_blob"] or blob_result["exit_code"]:
            differences.append({"file": name, "problem": "content differs or hash failed"})
    status = git("status", "--porcelain=v1")
    diff = git("diff", "--no-ext-diff", "--binary", "HEAD")
    selected_snapshot_guard = False
    selection_path = BASE / "source_selection.json"
    if selection_path.is_file():
        selection = json.loads(selection_path.read_text())
        snapshot = (BASE / selection.get("snapshot_path", "")).resolve()
        expected_original = baseline["files"]["traderBot\\main.cpp"]["sha256"]
        current_main = hashlib.sha256((ROOT / "traderBot" / "main.cpp").read_bytes()).hexdigest()
        selected_snapshot_guard = (
            selection.get("mode") == "original_audited_snapshot"
            and snapshot.is_relative_to(BASE) and snapshot.is_file()
            and selection.get("selected_main_sha256") == expected_original
            and hashlib.sha256(snapshot.read_bytes()).hexdigest() == expected_original
            and current_main == selection.get("observed_current_main_sha256")
            and all(d["file"] == "traderBot\\main.cpp" for d in differences)
        )
    result = {
        "original_files_checked": len(baseline["files"]),
        "sha256_and_git_blob_hashes_unchanged": not differences,
        "differences": differences,
        "git_status_after": status,
        "git_diff_after": diff,
        "tracked_file_verification_available": status["exit_code"] == 0,
        "production_unchanged_since_source_selection": selected_snapshot_guard,
        "selected_earlier_snapshot_verified": selected_snapshot_guard,
        "limitation": "The supplied folder has no Git repository. Git status/diff failed before and after; hashes verify the 20 original source/build/config files, not an unavailable tracked-file inventory.",
    }
    (BASE / "preservation_after.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("original_files_checked", "sha256_and_git_blob_hashes_unchanged", "tracked_file_verification_available", "production_unchanged_since_source_selection", "selected_earlier_snapshot_verified", "differences")}, indent=2))
    return not differences or selected_snapshot_guard


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(0 if verify() else 1)
