from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "implantacao" / "instalar_wordcraft_runtime.sh"


def test_imagem_instala_node_e_monta_bundle_somente_leitura():
    dockerfile = (ROOT / "implantacao" / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "implantacao" / "docker-compose.yml").read_text(encoding="utf-8")
    streamlit = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")

    assert "nodejs" in dockerfile
    assert "docs/wordcraft/upstream.lock.json ./docs/wordcraft/upstream.lock.json" in dockerfile
    assert "/opt/govdocs-wordcraft/wordcraft:/app/static/wordcraft:ro" in compose
    assert "enableStaticServing = true" in streamlit


def test_contexto_docker_inclui_somente_o_lock_wordcraft_necessario():
    rules = [line.strip() for line in (ROOT / ".dockerignore").read_text(
        encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    expected = ["docs/*", "!docs/wordcraft/", "docs/wordcraft/*",
                "!docs/wordcraft/upstream.lock.json"]
    positions = [rules.index(rule) for rule in expected]
    assert positions == sorted(positions)
    assert "docs/" not in rules


def test_instalador_recusa_promover_manifesto_de_qa():
    script = INSTALLER.read_text(encoding="utf-8")

    assert 'manifest.get("status") != "GOVCONNECT_WORDCRAFT_DEPLOY_APPROVED"' in script
    assert "artefato não aprovado para produção" in script
    assert "sha256sum" in script
    assert "hashlib.sha256(data).hexdigest()" in script


def test_instalacao_e_atomica_e_preserva_runtime_anterior():
    script = INSTALLER.read_text(encoding="utf-8")

    assert script.index('mv "$ROOT/wordcraft" "$previous"') < script.index(
        'mv "$next" "$ROOT/wordcraft"'
    )
    assert "GOVDOCS_WORDCRAFT_BUNDLE=/app/static/wordcraft" in script
    assert "GOVDOCS_WORDCRAFT_NODE=/usr/bin/node" in script
