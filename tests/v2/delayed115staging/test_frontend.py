"""用离线 API 替身验证前端保存门禁，不加载宿主或触发上传。"""
import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("outcome", ["rejected", "network", "invalid_success", "accepted"])
def test_save_requires_explicit_validation_success(outcome):
    node = shutil.which("node")
    assert node, "前端契约验证需要 Node.js"
    module = (Path(__file__).parents[3] / "plugins.v2/delayed115staging"
              / "frontend/src/components/shared.js")
    script = """
const { validateAndSave } = await import(process.argv[1]);
const outcome = process.argv[2];
const calls = [];
const emitted = [];
const api = { post: async (path, data) => {
  calls.push({path, data});
  if (outcome === 'network') throw new Error('offline');
  const success = outcome === 'accepted' ? true : outcome === 'invalid_success' ? 'true' : false;
  return {success, message: 'conflicting rules'};
}};
let error = '';
try {
  const config = {rules: [{directory: '/电影', delay_minutes: 60}]};
  await validateAndSave(api, 'Delayed115Staging_clone', config, (...args) => emitted.push(args));
} catch (failure) { error = failure.message; }
console.log(JSON.stringify({calls, emitted, error}));
"""
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script, module.as_uri(), outcome],
        check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout)
    assert result["calls"] == [{
        "path": "plugin/Delayed115Staging_clone/validate",
        "data": {"rules": [{"directory": "/电影", "delay_minutes": 60}]},
    }]
    if outcome == "accepted":
        assert result["emitted"] == [["save", result["calls"][0]["data"]]]
        assert result["error"] == ""
    else:
        assert result["emitted"] == []
        assert result["error"]


def test_federation_entry_exposes_config_and_page():
    root = Path(__file__).parents[3] / "plugins.v2/delayed115staging/dist/assets"
    entry = (root / "remoteEntry.js").read_text(encoding="utf-8")
    assert '"./Config"' in entry
    assert '"./Page"' in entry
    assert list(root.glob("__federation_expose_Config-*.js"))
    assert list(root.glob("__federation_expose_Page-*.js"))


def test_config_load_uses_host_route():
    root = (Path(__file__).parents[3] / "plugins.v2/delayed115staging"
            / "frontend/src/components")
    component = (root / "Config.vue").read_text(encoding="utf-8")
    assert "`plugin/${props.pluginId || PLUGIN_ID}`" in component
    assert "/get_config" not in component

    host = (Path(__import__("os").environ["MOVIEPILOT_BACKEND_PATH"]) / "app/api/endpoints/plugin.py").read_text(encoding="utf-8")
    handler = next(node for node in ast.parse(host).body
                   if isinstance(node, ast.AsyncFunctionDef) and node.name == "plugin_config")
    assert any(isinstance(decorator, ast.Call)
               and isinstance(decorator.func, ast.Attribute)
               and decorator.func.attr == "get"
               and decorator.args[0].value == "/{plugin_id}"
               for decorator in handler.decorator_list)


@pytest.mark.parametrize("enveloped", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("confirmation_mode", [None, "manual", "staging_deleted"])
def test_normalize_config_preserves_mappings_and_isolates_edits(enveloped, legacy, confirmation_mode):
    node = shutil.which("node")
    assert node, "前端契约验证需要 Node.js"
    module = (Path(__file__).parents[3] / "plugins.v2/delayed115staging"
              / "frontend/src/components/shared.js")
    first = {"library_root": "/pt1", "staging_root": "/115-staging1",
             "rules": [{"directory": "/", "delay_minutes": 60}]}
    second = {"library_root": "/pt2", "staging_root": "/115-staging2",
              "rules": [{"directory": "/动漫", "tiers": [
                  {"below_gb": 5, "delay_minutes": 10},
                  {"below_gb": None, "delay_minutes": 30}]}]}
    config = {"enabled": True, "cleanup_organized": True, "cleanup_empty_dirs": False}
    if confirmation_mode is not None:
        config["confirmation_mode"] = confirmation_mode
    config.update(first if legacy else {"mappings": [first, second]})
    response = {"success": True, "data": config} if enveloped else config
    script = """
const { normalizeConfig, validateAndSave } = await import(process.argv[1]);
const source = JSON.parse(process.argv[2]);
const before = JSON.stringify(source);
const config = normalizeConfig(source);
const normalized = JSON.parse(JSON.stringify(config));
config.mappings[0].rules[0].delay_minutes = 123;
const emitted = [];
await validateAndSave({post: async () => ({success: true})}, 'Delayed115Staging', config,
  (...args) => emitted.push(args));
config.mappings[0].library_root = '/edited-after-save';
console.log(JSON.stringify({normalized, unchanged: before === JSON.stringify(source), emitted}));
"""
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script, module.as_uri(), json.dumps(response)],
        check=True, capture_output=True, text=True,
    )
    result = json.loads(completed.stdout)
    expected = {"scan_once": False, "history_days": 7, "enabled": True, "cleanup_organized": True, "cleanup_empty_dirs": False,
                "confirmation_mode": "staging_deleted",
                "mappings": [first] if legacy else [first, second]}
    assert result["normalized"] == expected
    assert result["unchanged"] is True
    saved = result["emitted"][0][1]
    assert saved["confirmation_mode"] == ("staging_deleted")
    assert saved["mappings"][0]["library_root"] == "/pt1"
    assert saved["mappings"][0]["rules"][0]["delay_minutes"] == 123
    if not legacy:
        assert saved["mappings"][1] == second
