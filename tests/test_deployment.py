import json
import os
import shutil
import subprocess
import sys

import pytest

from app.config import ROOT
from scripts.check_deployment import check_deployment


@pytest.fixture
def deployment_fixture(tmp_path, corpus):
    root = tmp_path / "bundle"
    static = root / "app" / "static"
    static.mkdir(parents=True)
    for name in ("index.html", "app.js", "styles.css"):
        (static / name).write_text("fixture", encoding="utf-8")
    folder = root / "data" / "corpus"
    folder.mkdir(parents=True)
    (folder / "EXM.json").write_text(json.dumps(corpus), encoding="utf-8")
    return root, corpus


def test_deployment_preflight_accepts_a_bundled_corpus(deployment_fixture):
    root, _ = deployment_fixture
    assert check_deployment(root) == {"companies": 1, "chunks": 3}


def test_deployment_preflight_rejects_missing_frontend(deployment_fixture):
    root, _ = deployment_fixture
    (root / "app" / "static" / "app.js").unlink()
    with pytest.raises(ValueError, match="Missing frontend asset"):
        check_deployment(root)


def test_deployment_preflight_rejects_missing_index(deployment_fixture):
    root, _ = deployment_fixture
    (root / "data" / "corpus" / "EXM.json").unlink()
    with pytest.raises(ValueError, match="No filing indexes"):
        check_deployment(root)


@pytest.mark.parametrize("vector,reason", [
    ([1.0], "dimensions"),
    ([float("nan"), 0.0], "Invalid embedding"),
    ([2.0, 0.0], "not normalized"),
])
def test_deployment_preflight_rejects_broken_vectors(deployment_fixture, vector, reason):
    root, corpus = deployment_fixture
    corpus.update(embedding_model="example", dimensions=2)
    for chunk in corpus["chunks"]:
        chunk["embedding"] = vector
    (root / "data" / "corpus" / "EXM.json").write_text(json.dumps(corpus), encoding="utf-8")
    with pytest.raises(ValueError, match=reason):
        check_deployment(root)


def test_app_starts_from_bundle_without_env_files_or_writes(tmp_path):
    bundle = tmp_path / "isolated-bundle"
    shutil.copytree(ROOT / "app", bundle / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "data" / "corpus", bundle / "data" / "corpus")
    before = {p.relative_to(bundle) for p in bundle.rglob("*") if p.is_file()}
    env = os.environ.copy()
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "DOCULENS_INDEX_DIR", "DOCULENS_API_TOKEN",
                 "DOCULENS_PUBLIC_DEMO", "PYTHONPATH"):
        env.pop(name, None)
    env.update(VERCEL="1", PYTHONDONTWRITEBYTECODE="1")
    code = """
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
with patch('app.llm.requests.post', side_effect=AssertionError('Unexpected provider call')):
    client = TestClient(app)
    assert client.get('/health').status_code == 200
    assert client.get('/').status_code == 200
    assert client.get('/assets/app.js').status_code == 200
    assert client.get('/assets/styles.css').status_code == 200
    catalog = client.get('/corpus').json()
    assert catalog['tickers'][0]['ticker'] == 'NVDA'
    assert catalog['tickers'][0]['retrieval'] == 'hybrid'
    assert not catalog['answering_configured']
    response = client.post('/query', json={'ticker': 'NVDA', 'question': 'What was revenue?'})
    assert response.status_code == 503
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=bundle, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert {p.relative_to(bundle) for p in bundle.rglob("*") if p.is_file()} == before
    assert not (bundle / ".env").exists()


def test_vercel_build_hook_and_bundle_include_serving_assets():
    import tomllib
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["vercel"]["scripts"]["build"] == "python scripts/check_deployment.py"
    config = json.loads((ROOT / "vercel.json").read_text())
    include = config["functions"]["app/main.py"]["includeFiles"]
    assert "app/static/**" in include and "data/corpus/**" in include
