from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_IDS = (
    "embylibraryorganizer",
    "mediametadatasync",
    "directoryfilesearch",
)


def read_component(plugin_id: str, component: str) -> str:
    """读取指定插件的 Vue 组件源码。"""
    return (
        ROOT
        / "frontend"
        / plugin_id
        / "src"
        / "components"
        / component
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize("plugin_id", PLUGIN_IDS)
def test_plugin_page_uses_shared_workbench_contract(plugin_id: str) -> None:
    """三个插件主页面应遵循统一工作台与可访问性合同。"""
    source = read_component(plugin_id, "Page.vue")

    assert 'class="plugin-workbench' in source
    assert 'class="metric-grid"' in source
    assert 'aria-label="刷新插件状态"' in source
    assert 'aria-label="打开插件设置"' in source
    assert 'aria-label="关闭插件页面"' in source
    assert 'aria-live="polite"' in source
    assert "min-height: 44px" in source
    assert "letter-spacing: 0" in source
    assert "rgba(var(--v-theme-on-surface), 0.72)" in source
    assert "@media (prefers-reduced-motion: reduce)" in source


@pytest.mark.parametrize("plugin_id", PLUGIN_IDS)
def test_plugin_config_uses_shared_form_contract(plugin_id: str) -> None:
    """三个插件配置页应遵循统一表单与辅助信息合同。"""
    source = read_component(plugin_id, "Config.vue")

    assert 'class="plugin-config' in source
    assert 'aria-label="关闭插件设置"' in source
    assert 'class="field-help"' in source
    assert "min-width: 44px" in source
    assert "min-height: 44px" in source
    assert "letter-spacing: 0" in source
    assert "@media (prefers-reduced-motion: reduce)" in source
