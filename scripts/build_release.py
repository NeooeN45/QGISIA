# -*- coding: utf-8 -*-
"""
build_release — construit l'artefact QGISIA2 depuis la source VERSIONNÉE.

Pourquoi ce script existe : `releases/` et `*.zip` sont ignorés par git, et
l'artefact v3.9 avait été assemblé à la main. Rien ne garantissait donc que le
ZIP livré corresponde au code du dépôt — et de fait, v3.9 embarquait un
`__pycache__/` et 98 Mo de `vendor/`, tout en étant plus ANCIEN que la source.

Deux propriétés sont assurées ici :

1. **Source unique** — le contenu est lu depuis les blobs git (`git cat-file`),
   pas depuis le worktree. Un fichier non commité ne peut pas entrer dans
   l'artefact, et les fins de ligne sont celles du dépôt : le ZIP est donc
   identique qu'on le construise sous Windows ou sous Linux.
2. **Reproductibilité** — entrées triées, horodatage figé, permissions figées,
   niveau de compression figé. Deux constructions successives du même commit
   donnent le même SHA-256, ce qui rend l'artefact vérifiable par un tiers.

Usage :
    python scripts/build_release.py --output releases/QGISIA2_v3.10.zip
    python scripts/build_release.py --check-reproducible
    python scripts/build_release.py --inspect releases/QGISIA2_v3.10.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile

# Préfixe des fichiers embarqués (le plugin QGIS attend ce dossier racine).
PLUGIN_DIR = "QGISIA2"

# Horodatage figé de toutes les entrées : 1980-01-01, plancher du format ZIP.
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

# Permissions figées : -rw-r--r--
FIXED_EXTERNAL_ATTR = (0o100644 << 16)

COMPRESS_LEVEL = 9

# Chemins exclus même s'ils étaient versionnés par accident.
EXCLUDED_FRAGMENTS = ("__pycache__/", ".pyc", ".pyo", "/vendor/", "/data/")

# Motifs dont la présence dans l'artefact final est une régression de sécurité.
# Ils correspondent aux chemins supprimés par le durcissement du bridge.
FORBIDDEN_PATTERNS = (
    ('"/api/qgis/runScriptDirect"', "route d'exécution sans confirmation"),
    ("def runScriptDirect", "slot d'exécution sans confirmation"),
    ('"__builtins__": __builtins__', "builtins complets passés à un contexte d'exécution"),
    ("exec(self.script", "exec du script dans le processus QGIS"),
)


def _git(repo, *args, binary=False):
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, check=True
    )
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def versioned_files(repo, ref="HEAD"):
    """Chemins versionnés du plugin, triés, hors artefacts de build."""
    listing = _git(repo, "ls-tree", "-r", "--name-only", ref, PLUGIN_DIR)
    files = [line for line in listing.splitlines() if line.strip()]
    kept = [
        path for path in files
        if not any(fragment in f"/{path}" for fragment in EXCLUDED_FRAGMENTS)
    ]
    return sorted(kept)


def build_info(repo, ref="HEAD"):
    """Provenance de l'artefact — déterministe pour un commit donné."""
    return {
        "plugin": PLUGIN_DIR,
        "source": "git",
        "commit": _git(repo, "rev-parse", ref),
        "commit_date": _git(repo, "show", "-s", "--format=%cI", ref),
        "built_from": "scripts/build_release.py",
        "note": (
            "Artefact reproductible : reconstruire ce commit doit redonner "
            "le meme SHA-256."
        ),
    }


def _add(archive, name, data):
    entry = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = FIXED_EXTERNAL_ATTR
    entry.create_system = 3  # unix, figé (sinon dépend de la plateforme)
    archive.writestr(entry, data, compresslevel=COMPRESS_LEVEL)


def build_archive(output, repo=".", ref="HEAD"):
    """Construit l'archive et retourne son SHA-256."""
    repo = os.path.abspath(repo)
    files = versioned_files(repo, ref)
    if not files:
        raise SystemExit(
            f"Aucun fichier versionne sous {PLUGIN_DIR}/ au ref {ref}. "
            "La source canonique est-elle bien commitee ?"
        )

    payload = {path: _git(repo, "cat-file", "blob", f"{ref}:{path}", binary=True)
               for path in files}
    payload[f"{PLUGIN_DIR}/BUILD_INFO.json"] = json.dumps(
        build_info(repo, ref), indent=2, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")

    output = os.path.abspath(str(output))
    os.makedirs(os.path.dirname(output), exist_ok=True)
    # `zipfile` n'écrit aucun horodatage global : le fichier est donc
    # entierement determine par ses entrees.
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payload):
            _add(archive, name, payload[name])

    return sha256_of(output)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_archive(path):
    """Cherche les motifs interdits dans les .py de l'archive.

    Retourne la liste des constats (vide = artefact conforme).
    """
    findings = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.endswith(".py"):
                continue
            try:
                text = archive.read(name).decode("utf-8", "replace")
            except KeyError:  # pragma: no cover
                continue
            for pattern, label in FORBIDDEN_PATTERNS:
                if pattern in text:
                    findings.append(f"{name}: {label} — motif {pattern!r}")
    return findings


def check_reproducible(repo=".", ref="HEAD"):
    """Construit deux fois et compare. Retourne (ok, sha1, sha2)."""
    with tempfile.TemporaryDirectory() as tmp:
        first = os.path.join(tmp, "first.zip")
        second = os.path.join(tmp, "second.zip")
        sha1 = build_archive(first, repo=repo, ref=ref)
        sha2 = build_archive(second, repo=repo, ref=ref)
    return sha1 == sha2, sha1, sha2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="chemin du ZIP a produire")
    parser.add_argument("--repo", default=".", help="racine du depot")
    parser.add_argument("--ref", default="HEAD", help="reference git a empaqueter")
    parser.add_argument("--check-reproducible", action="store_true",
                        help="construit deux fois et compare les SHA-256")
    parser.add_argument("--inspect", help="inspecte un ZIP existant")
    args = parser.parse_args(argv)

    if args.inspect:
        findings = inspect_archive(args.inspect)
        if findings:
            print("ARTEFACT NON CONFORME :")
            for finding in findings:
                print(f"  - {finding}")
            return 1
        print(f"OK : aucun motif interdit dans {args.inspect}")
        return 0

    if args.check_reproducible:
        ok, sha1, sha2 = check_reproducible(args.repo, args.ref)
        print(f"build 1 : {sha1}")
        print(f"build 2 : {sha2}")
        if not ok:
            print("ECHEC : la construction n'est pas reproductible.")
            return 1
        print("OK : construction reproductible.")
        return 0

    if not args.output:
        parser.error("--output est requis (ou utiliser --check-reproducible / --inspect)")

    digest = build_archive(args.output, repo=args.repo, ref=args.ref)
    with open(f"{args.output}.sha256", "w", encoding="utf-8") as handle:
        handle.write(f"{digest}  {os.path.basename(args.output)}\n")

    findings = inspect_archive(args.output)
    if findings:
        print("ARTEFACT NON CONFORME :")
        for finding in findings:
            print(f"  - {finding}")
        return 1

    size = os.path.getsize(args.output)
    print(f"{args.output}")
    print(f"  SHA-256 : {digest}")
    print(f"  taille  : {size / 1e6:.1f} Mo")
    print("  inspection securite : OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
