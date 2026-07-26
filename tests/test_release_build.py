# -*- coding: utf-8 -*-
"""Tests du constructeur d'artefact de release.

Exigences couvertes :
- l'archive est construite UNIQUEMENT depuis la source versionnée (les blobs
  git, pas le worktree) : un fichier non commité ne peut pas s'y glisser, et
  le résultat est identique sur Windows et sur Linux malgré les fins de ligne ;
- deux constructions successives produisent le même SHA-256 ;
- les artefacts de build (__pycache__, .pyc, vendor/, data/) sont absents ;
- les routes interdites ne sont pas présentes dans l'archive finale.
"""
import hashlib
import os
import subprocess
import sys
import zipfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import build_release as br  # noqa: E402


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("release") / "QGISIA2_test.zip"
    br.build_archive(out, repo=REPO)
    return out


# ── Reproductibilité ──────────────────────────────────────────────────────────

def test_two_builds_are_byte_identical(tmp_path):
    first = tmp_path / "a.zip"
    second = tmp_path / "b.zip"
    br.build_archive(first, repo=REPO)
    br.build_archive(second, repo=REPO)
    assert _sha256(first) == _sha256(second)


def test_all_entries_have_a_fixed_timestamp(built):
    with zipfile.ZipFile(built) as archive:
        stamps = {info.date_time for info in archive.infolist()}
    assert stamps == {br.FIXED_TIMESTAMP}, stamps


def test_all_entries_have_fixed_permissions(built):
    with zipfile.ZipFile(built) as archive:
        attrs = {info.external_attr for info in archive.infolist()}
    assert len(attrs) == 1, "permissions non déterministes"


def test_entries_are_sorted(built):
    with zipfile.ZipFile(built) as archive:
        names = archive.namelist()
    assert names == sorted(names)


# ── Contenu ───────────────────────────────────────────────────────────────────

def test_archive_contains_the_plugin_sources(built):
    with zipfile.ZipFile(built) as archive:
        names = set(archive.namelist())
    for expected in (
        "QGISIA2/geoai_assistant.py",
        "QGISIA2/bridge_http.py",
        "QGISIA2/script_validation.py",
        "QGISIA2/script_sandbox.py",
        "QGISIA2/sandbox_runner.py",
        "QGISIA2/script_commands.py",
        "QGISIA2/metadata.txt",
    ):
        assert expected in names, f"absent de l'archive : {expected}"


def test_archive_has_a_single_top_level_directory(built):
    with zipfile.ZipFile(built) as archive:
        tops = {name.split("/")[0] for name in archive.namelist()}
    assert tops == {"QGISIA2"}, tops


EXCLUDED_FRAGMENTS = ("__pycache__", ".pyc", ".pyo", "/vendor/", "/data/", "/.git")


def test_build_artefacts_are_excluded(built):
    with zipfile.ZipFile(built) as archive:
        names = archive.namelist()
    for name in names:
        for fragment in EXCLUDED_FRAGMENTS:
            assert fragment not in name, f"artefact de build embarqué : {name}"


def test_build_info_records_the_source_commit(built):
    with zipfile.ZipFile(built) as archive:
        info = archive.read("QGISIA2/BUILD_INFO.json").decode("utf-8")
    assert "commit" in info
    assert "git" in info


def test_uncommitted_file_is_not_embedded(built, tmp_path):
    # Une trace non versionnée dans le worktree ne doit pas atteindre l'archive.
    stray = os.path.join(REPO, "QGISIA2", "_non_versionne_test.py")
    with open(stray, "w", encoding="utf-8") as handle:
        handle.write("# fichier non commite\n")
    try:
        out = tmp_path / "c.zip"
        br.build_archive(out, repo=REPO)
        with zipfile.ZipFile(out) as archive:
            names = archive.namelist()
        assert not any("_non_versionne_test" in n for n in names)
    finally:
        os.remove(stray)


# ── Inspection de sécurité de l'artefact ─────────────────────────────────────

def test_final_archive_has_no_forbidden_route(built):
    findings = br.inspect_archive(built)
    assert findings == [], findings


def test_inspection_actually_detects_a_forbidden_route(tmp_path):
    # Test négatif : si l'inspecteur ne détectait rien, le test précédent
    # serait vide de sens.
    poisoned = tmp_path / "poisoned.zip"
    with zipfile.ZipFile(poisoned, "w") as archive:
        archive.writestr(
            "QGISIA2/geoai_assistant.py",
            'elif route == "/api/qgis/runScriptDirect":\n',
        )
    findings = br.inspect_archive(poisoned)
    assert findings
    assert any("runScriptDirect" in f for f in findings)


def test_inspection_detects_full_builtins_context(tmp_path):
    poisoned = tmp_path / "poisoned2.zip"
    with zipfile.ZipFile(poisoned, "w") as archive:
        archive.writestr(
            "QGISIA2/geoai_assistant.py",
            'context = {"__builtins__": __builtins__}\n',
        )
    findings = br.inspect_archive(poisoned)
    assert findings


def test_inspection_detects_a_reintroduced_direct_slot(tmp_path):
    poisoned = tmp_path / "poisoned3.zip"
    with zipfile.ZipFile(poisoned, "w") as archive:
        archive.writestr(
            "QGISIA2/geoai_assistant.py",
            "    def runScriptDirect(self, script):\n        return 1\n",
        )
    findings = br.inspect_archive(poisoned)
    assert findings


# ── Cohérence avec la source ─────────────────────────────────────────────────

def test_archive_matches_the_committed_blobs(built):
    # L'archive doit contenir exactement l'octet-à-octet de git, pour que
    # l'artefact soit vérifiable à partir du dépôt seul.
    blob = subprocess.run(
        ["git", "show", "HEAD:QGISIA2/bridge_http.py"],
        cwd=REPO, capture_output=True, check=True,
    ).stdout
    with zipfile.ZipFile(built) as archive:
        embedded = archive.read("QGISIA2/bridge_http.py")
    assert embedded == blob
