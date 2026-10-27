"""Promove um bundle QA somente após reconciliar as provas imutáveis do CI."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


QA_STATUS = "INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED"
RELEASE_STATUS = "GOVCONNECT_WORDCRAFT_DEPLOY_APPROVED"
BUILD_WORKFLOW = ".github/workflows/wordcraft-build.yml"
FIDELITY_WORKFLOW = ".github/workflows/wordcraft-fidelity.yml"


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON inválido: {path.name}")
    return value


def _run(run: dict, workflow: str) -> tuple[int, str]:
    if (run.get("path") != workflow or run.get("status") != "completed"
            or run.get("conclusion") != "success"):
        raise ValueError(f"workflow não aprovado: {workflow}")
    run_id = run.get("id")
    sha = run.get("head_sha")
    if type(run_id) is not int or not re.fullmatch(r"[0-9a-f]{40}", str(sha or "")):
        raise ValueError("identidade do workflow inválida")
    return run_id, sha


def _artifact(inventory: dict, name: str, run_id: int) -> dict:
    matches = [item for item in inventory.get("artifacts", [])
               if item.get("name") == name and not item.get("expired")]
    if len(matches) != 1:
        raise ValueError(f"artefato obrigatório ausente ou ambíguo: {name}")
    item = matches[0]
    if item.get("workflow_run", {}).get("id") != run_id:
        raise ValueError("artefato pertence a outra execução")
    digest = item.get("digest")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(digest or "")):
        raise ValueError("digest do artefato inválido")
    return {"id": item.get("id"), "name": name, "digest": digest}


def promover(bundle: Path, build_run_path: Path, build_artifacts_path: Path,
             fidelity_run_path: Path, fidelity_artifacts_path: Path,
             fidelity_artifact_id: int, fidelity_artifact_digest: str,
             approval_commit: str, output: Path) -> dict:
    build_id, producer = _run(_json(build_run_path), BUILD_WORKFLOW)
    fidelity_id, fidelity_sha = _run(_json(fidelity_run_path), FIDELITY_WORKFLOW)
    if producer != fidelity_sha:
        raise ValueError("build e fidelidade não usam o mesmo commit")
    if not re.fullmatch(r"[0-9a-f]{40}", approval_commit):
        raise ValueError("commit de aprovação inválido")

    build_artifact = _artifact(_json(build_artifacts_path),
                               "wordcraft-govconnect-local-qa", build_id)
    expected_prefix = f"wordcraft-synthetic-fidelity-{fidelity_id}-"
    fidelity_matches = [item for item in _json(fidelity_artifacts_path).get("artifacts", [])
                        if (item.get("id") == fidelity_artifact_id
                            and item.get("digest") == fidelity_artifact_digest
                            and str(item.get("name", "")).startswith(expected_prefix)
                            and item.get("workflow_run", {}).get("id") == fidelity_id
                            and not item.get("expired"))]
    if len(fidelity_matches) != 1:
        raise ValueError("prova de fidelidade fixada ausente ou divergente")
    fidelity_artifact = {
        "id": fidelity_artifact_id,
        "name": fidelity_matches[0]["name"],
        "digest": fidelity_artifact_digest,
    }

    manifest_path = bundle / "qa-manifest.json"
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("status") != QA_STATUS or manifest.get("govconnect_commit") != producer:
        raise ValueError("bundle QA não corresponde ao build aprovado")
    files = manifest.get("files")
    if not isinstance(files, list) or not 2 <= len(files) <= 100:
        raise ValueError("inventário do bundle inválido")
    seen: set[str] = set()
    for item in files:
        name = item.get("path")
        if (not isinstance(name, str) or name in seen or name.startswith("/")
                or any(part in {"", ".", ".."} for part in name.split("/"))):
            raise ValueError("caminho inválido no bundle")
        seen.add(name)
        path = (bundle / name).resolve()
        if not path.is_relative_to(bundle.resolve()) or not path.is_file():
            raise ValueError("asset ausente no bundle")
        data = path.read_bytes()
        if len(data) != item.get("bytes") or hashlib.sha256(data).hexdigest() != item.get("sha256"):
            raise ValueError("asset divergiu do manifesto")
    notices = _json(bundle / "notices" / "manifest.json")
    if (notices.get("status") != "UPSTREAM_AND_FONT_NOTICES_VERIFIED"
            or notices.get("upstream_commit") != manifest.get("upstream_commit")):
        raise ValueError("avisos de distribuição não reconciliados")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for name in seen:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle / name, target)
    shutil.copytree(bundle / "notices", output / "notices")
    manifest["status"] = RELEASE_STATUS
    manifest["distribution_review"] = "CI build, browser, native export, notices and synthetic fidelity gates reconciled."
    manifest["release_evidence"] = {
        "approval_commit": approval_commit,
        "build_run_id": build_id,
        "build_artifact": build_artifact,
        "fidelity_run_id": fidelity_id,
        "fidelity_artifact": fidelity_artifact,
    }
    promoted = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    (output / "qa-manifest.json").write_bytes(promoted)
    return {"status": RELEASE_STATUS, "producer_commit": producer,
            "approval_commit": approval_commit,
            "manifest_sha256": hashlib.sha256(promoted).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--build-run", type=Path, required=True)
    parser.add_argument("--build-artifacts", type=Path, required=True)
    parser.add_argument("--fidelity-run", type=Path, required=True)
    parser.add_argument("--fidelity-artifacts", type=Path, required=True)
    parser.add_argument("--fidelity-artifact-id", type=int, required=True)
    parser.add_argument("--fidelity-artifact-digest", required=True)
    parser.add_argument("--approval-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(promover(args.bundle.resolve(), args.build_run,
                              args.build_artifacts, args.fidelity_run,
                              args.fidelity_artifacts, args.fidelity_artifact_id,
                              args.fidelity_artifact_digest, args.approval_commit,
                              args.output.resolve()), sort_keys=True))


if __name__ == "__main__":
    main()
