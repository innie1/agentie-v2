from pathlib import Path


def test_frontend_uses_react_typescript_vite_and_pwa_build():
    root = Path("frontend")
    package = (root / "package.json").read_text(encoding="utf-8")
    app = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    config = (root / "vite.config.ts").read_text(encoding="utf-8")
    assert '"react"' in package
    assert '"typescript"' in package
    assert "VitePWA" in config
    assert 'id="persistentAgentList"' in app
    assert 'id="messages"' in app
    assert 'id="messageInput"' in app
    assert 'id="sendButton"' in app


def test_production_frontend_build_is_present():
    dist = Path("frontend/dist")
    index = (dist / "index.html").read_text(encoding="utf-8")
    assert "manifest.webmanifest" in index
    assert any((dist / "assets").glob("index-*.js"))
    assert (dist / "sw.js").is_file()
