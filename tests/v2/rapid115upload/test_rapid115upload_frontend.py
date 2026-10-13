"""后处理前端配置及任务操作的离线契约测试。"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3] / 'plugins.v2/rapid115upload'


@pytest.mark.parametrize("mode", ["off", "strm", "cd2"])
def test_postprocess_config_roundtrip_defaults_and_isolation(mode):
    """升级默认为关闭，模式与映射保存时不污染宿主或其他插件实例。"""
    script = """
const {normalizeConfig, validateAndSave} = await import(process.argv[1]);
const source = {postprocess:{mode:process.argv[2],mappings:[{source_root:'/影视库',
 strm_root:'/media/strm',playback_root:'/CloudNAS/CloudDrive/115open/影视库',cd2_root:'/115open/影视库'}]}};
const config=normalizeConfig(source), other=normalizeConfig(source);
let saved, endpoint;
await validateAndSave({post:async(path)=>{endpoint=path;return {success:true}}},'clone',config,(_,payload)=>{saved=payload});
config.postprocess.mappings[0].source_root='/changed';
config.postprocess.mode='off';
console.log(JSON.stringify({saved,source,other,endpoint,defaults:normalizeConfig({}).postprocess}));
"""
    result = subprocess.run(
        [shutil.which('node'), '--input-type=module', '-e', script,
         (ROOT / 'frontend/src/components/shared.js').as_uri(), mode],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    assert data['endpoint'] == 'plugin/clone/validate'
    assert data['saved']['postprocess'] == data['other']['postprocess']
    assert data['saved']['postprocess']['mode'] == mode
    assert data['saved']['postprocess']['mappings'] == data['source']['postprocess']['mappings']
    assert data['defaults'] == {
        'mode': 'off', 'mappings': [], 'cd2_plugin_id': 'CloudDriveDisk',
        'merge_delay': 45, 'max_wait': 180, 'min_interval': 3,
    }


def test_postprocess_actions_keep_upload_and_frozen_configuration_separate():
    """按钮不允许把完成任务切换模式重复处理，失败不重试，补处理显式选用当前配置。"""
    script = """
import assert from 'node:assert/strict';
const {postprocessAction} = await import(process.argv[1]);
for (const state of ['waiting','running','blocked','cancelled']) {
 assert.equal(postprocessAction({state}), '');
}
assert.equal(postprocessAction(null), '');
assert.equal(postprocessAction({state:'uploaded'}), 'post_enqueue');
assert.equal(postprocessAction({state:'uploaded',postprocess:{state:'disabled'}}), 'post_enqueue');
assert.equal(postprocessAction({state:'uploaded',postprocess:{state:'failed',attempts:0}}), 'post_enqueue');
for (const state of ['failed','retry','conflict']) {
 assert.equal(postprocessAction({state:'uploaded',postprocess:{state,target:'/target'}}), '');
}
for (const state of ['done','skipped','pending','running']) {
 assert.equal(postprocessAction({state:'uploaded',postprocess:{state,target:'/target'}}), '');
}
assert.equal(postprocessAction({state:'uploaded',postprocess:{state:'failed',attempts:2}}), '');
"""
    subprocess.run(
        [shutil.which('node'), '--input-type=module', '-e', script,
         (ROOT / 'frontend/src/components/shared.js').as_uri()],
        check=True, capture_output=True, text=True,
    )
    page = (ROOT / 'frontend/src/components/Page.vue').read_text()
    assert '@click="act(postAction)"' in page
    assert 'postprocess_stats' in page
    assert 'RPC 次数不是115 API请求次数' in page
    config = (ROOT / 'frontend/src/components/Config.vue').read_text()
    assert 'v-radio-group v-model="config.postprocess.mode"' in config
    assert "v-if=\"config.postprocess.mode === 'strm'\"" in config
    assert '<v-radio label="定向刷新 CD2' in config
    assert 'postTimingFields' not in config
