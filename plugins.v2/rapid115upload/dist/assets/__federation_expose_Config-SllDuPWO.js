import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { P as PLUGIN_ID, n as normalizeConfig, l as libraryOptions, q as qbOptions, v as validateAndSave } from './shared-yLuSZolc.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,createVNode:_createVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,vShow:_vShow,withDirectives:_withDirectives,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "upload-config" };
const _hoisted_2 = ["disabled"];
const _hoisted_3 = {
  "aria-label": "基本设置",
  class: "config-panel"
};
const _hoisted_4 = { class: "switch-row" };
const _hoisted_5 = { class: "field-grid" };
const _hoisted_6 = { class: "config-field" };
const _hoisted_7 = { class: "config-field" };
const _hoisted_8 = {
  "aria-label": "目录映射",
  class: "config-panel"
};
const _hoisted_9 = {
  key: 1,
  class: "field-help"
};
const _hoisted_10 = { class: "mapping-toolbar" };
const _hoisted_11 = {
  key: 1,
  class: "field-help"
};
const _hoisted_12 = { class: "config-field" };
const _hoisted_13 = {
  key: 0,
  class: "field-help text-error"
};
const _hoisted_14 = { class: "config-field" };
const _hoisted_15 = { class: "config-field" };
const _hoisted_16 = { class: "config-field" };
const _hoisted_17 = { class: "config-field" };
const _hoisted_18 = { class: "retry-grid" };
const _hoisted_19 = ["for"];
const _hoisted_20 = { class: "retry-input" };
const _hoisted_21 = { class: "mapping-bottom" };
const _hoisted_22 = {
  key: 3,
  class: "empty-mappings"
};
const _hoisted_23 = {
  "aria-label": "qB标签设置",
  class: "config-panel"
};
const _hoisted_24 = { class: "switch-row" };
const _hoisted_25 = {
  key: 1,
  class: "field-help"
};
const _hoisted_26 = { class: "config-field" };
const _hoisted_27 = { class: "field-grid" };
const _hoisted_28 = { class: "config-field" };
const _hoisted_29 = { class: "config-field" };
const _hoisted_30 = {
  "aria-label": "BDMV上传设置",
  class: "config-panel"
};
const _hoisted_31 = { class: "switch-row" };
const _hoisted_32 = { class: "field-grid" };
const _hoisted_33 = { class: "config-field" };
const _hoisted_34 = { class: "config-field" };
const _hoisted_35 = { class: "config-field" };
const _hoisted_36 = { class: "mapping-toolbar" };
const _hoisted_37 = {
  key: 1,
  class: "field-help"
};
const _hoisted_38 = ["for"];
const _hoisted_39 = { class: "field-help" };
const _hoisted_40 = { class: "config-footer" };

const {computed,onMounted,reactive,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: [Object, Function], default: () => ({}) },
  pluginId: { type: String, default: PLUGIN_ID },
},
  emits: ['save', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const config = reactive(normalizeConfig(props.initialConfig));
const afterUpload = computed({
  get: () => config.delete_after_upload ? (config.remove_empty_parents ? 'delete_empty' : 'delete') : 'keep',
  set: value => {
    config.delete_after_upload = value !== 'keep';
    config.remove_empty_parents = value === 'delete_empty';
  },
});
const loading = ref(true);
const loadFailed = ref(false);
const saving = ref(false);
const error = ref('');
const downloaders = ref([]);
const downloaderError = ref('');
async function loadDownloaders() {
  downloaderError.value = '';
  try {
    downloaders.value = qbOptions(await props.api.get('download/clients'));
  } catch (failure) {
    downloaders.value = [];
    downloaderError.value = failure?.message || '读取下载器失败';
  }
}
const directories = ref([]);
const directoryError = ref('');
async function loadDirectories() {
  directoryError.value = '';
  try {
    directories.value = libraryOptions(await props.api.get('storage/directories', {
      params: { directory_type: 'library', storage_type: 'local' },
    }));
  } catch (failure) {
    directories.value = [];
    directoryError.value = failure?.message || '读取目录管理失败';
  }
}
const tab = ref('general');
const bdmvMappingIndex = ref(0);
const bdmvMapping = computed(() => config.bdmv.mappings[bdmvMappingIndex.value]);
const bdmvMappingOptions = computed(() => config.bdmv.mappings.map((item, index) => ({ title: `${index + 1}. ${item.local_root || '新目录映射'}`, value: index })));
const bdmvFields = [
  { key: 'local_root', title: 'MP可见下载根目录', example: '/downloads', help: '使用 MP 下载器路径映射转换后的目录。' },
  { key: 'cd2_source_root', title: 'CD2本地存储根目录', example: '/本地存储/downloads', help: 'CD2 文件列表中的本地源目录，并非系统挂载点。' },
  { key: 'cd2_target_root', title: 'CD2中的115目标根目录', example: '/115/原盘', help: '保留下载根下的相对目录；目标父目录不存在时自动创建。' },
];
function addBdmvMapping() {
  config.bdmv.mappings.push({ local_root: '', cd2_source_root: '', cd2_target_root: '' });
  bdmvMappingIndex.value = config.bdmv.mappings.length - 1;
}
function removeBdmvMapping() {
  config.bdmv.mappings.splice(bdmvMappingIndex.value, 1);
  bdmvMappingIndex.value = Math.max(0, bdmvMappingIndex.value - 1);
}
const mappingIndex = ref(0);
const mapping = computed(() => config.mappings[mappingIndex.value]);
const mappingOptions = computed(() => config.mappings.map((item, index) => ({
  title: `${index + 1}. ${item.library_root || '新目录映射'}`,
  value: index,
})));
function addMapping() {
  config.mappings.push({ library_root: '', remote_root: '', max_attempts: 3, initial_delay_minutes: 0, retry_minutes: [60, 360, 1440] });
  mappingIndex.value = config.mappings.length - 1;
}
function removeMapping() {
  config.mappings.splice(mappingIndex.value, 1);
  mappingIndex.value = Math.max(0, Math.min(mappingIndex.value, config.mappings.length - 1));
}

async function save() {
  if (loading.value || loadFailed.value || saving.value) return
  if (config.mappings.some(item => !directories.value.some(option => option.value === item.library_root))) {
    tab.value = 'mappings';
    error.value = '请为每组映射选择MP目录管理中的本地整理目标';
    return
  }
  if (config.qb_enabled && (downloaderError.value || config.downloaders.some(
    name => !downloaders.value.some(option => option.value === name)
  ))) {
    tab.value = 'qb';
    error.value = '请重新读取并选择当前已启用的qB下载器';
    return
  }
  if (config.bdmv.enabled && (downloaderError.value || !config.bdmv.downloaders.length || config.bdmv.downloaders.some(name => !downloaders.value.some(option => option.value === name)))) {
    tab.value = 'bdmv';
    error.value = '请选择当前已启用的BDMV下载器';
    return
  }
  saving.value = true;
  error.value = '';
  try {
    await validateAndSave(props.api, props.pluginId, config, emit);
  } catch (failure) {
    error.value = failure?.message || String(failure);
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  try {
    const result = await props.api.get(`plugin/${props.pluginId || PLUGIN_ID}`);
    Object.assign(config, normalizeConfig(result));
    await Promise.all([loadDirectories(), loadDownloaders()]);
  } catch (failure) {
    loadFailed.value = true;
    error.value = `读取配置失败，请重新打开配置页：${failure?.message || failure}`;
  } finally {
    loading.value = false;
  }
});

return (_ctx, _cache) => {
  const _component_v_tab = _resolveComponent("v-tab");
  const _component_v_tabs = _resolveComponent("v-tabs");
  const _component_v_progress_linear = _resolveComponent("v-progress-linear");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_combobox = _resolveComponent("v-combobox");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _cache[65] || (_cache[65] = _createElementVNode("header", { class: "config-header" }, [
      _createElementVNode("div", { class: "config-title" }, "媒体整理增强"),
      _createElementVNode("p", { class: "config-subtitle" }, "本地整理完成后，按目录映射上传115")
    ], -1)),
    _createVNode(_component_v_tabs, {
      modelValue: tab.value,
      "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((tab).value = $event)),
      color: "primary",
      density: "compact",
      class: "config-tabs",
      grow: ""
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_tab, { value: "general" }, {
          default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
            _createTextVNode("基本设置", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_v_tab, { value: "mappings" }, {
          default: _withCtx(() => [
            _createTextVNode("目录映射 · " + _toDisplayString(config.mappings.length), 1)
          ]),
          _: 1
        }),
        _createVNode(_component_v_tab, { value: "qb" }, {
          default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
            _createTextVNode("qB 标签", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_v_tab, { value: "bdmv" }, {
          default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
            _createTextVNode("BDMV 上传", -1)
          ]))]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"]),
    (loading.value)
      ? (_openBlock(), _createBlock(_component_v_progress_linear, {
          key: 0,
          indeterminate: ""
        }))
      : _createCommentVNode("", true),
    (error.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 1,
          type: "error",
          variant: "tonal",
          density: "compact",
          class: "config-error"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    _createElementVNode("fieldset", {
      disabled: loading.value || saving.value || loadFailed.value,
      class: "config-body"
    }, [
      _withDirectives(_createElementVNode("section", _hoisted_3, [
        _createElementVNode("div", _hoisted_4, [
          _cache[23] || (_cache[23] = _createElementVNode("div", null, [
            _createElementVNode("strong", null, "启用插件"),
            _createElementVNode("p", null, "接收新的整理事件，并处理上传队列")
          ], -1)),
          _createVNode(_component_v_switch, {
            modelValue: config.enabled,
            "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((config.enabled) = $event)),
            "aria-label": "启用插件",
            color: "primary",
            density: "compact",
            "hide-details": ""
          }, null, 8, ["modelValue"])
        ]),
        _createElementVNode("div", _hoisted_5, [
          _createElementVNode("div", _hoisted_6, [
            _cache[24] || (_cache[24] = _createElementVNode("label", {
              class: "field-label",
              for: "rapid-concurrency"
            }, "同时处理数", -1)),
            _createVNode(_component_v_text_field, {
              id: "rapid-concurrency",
              modelValue: config.concurrency,
              "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.concurrency) = $event)),
              modelModifiers: { number: true },
              "aria-label": "同时处理数",
              type: "number",
              min: "1",
              max: "16",
              variant: "outlined",
              density: "compact",
              "hide-details": ""
            }, null, 8, ["modelValue"]),
            _cache[25] || (_cache[25] = _createElementVNode("p", { class: "field-help" }, "默认2个，等待重试不占用名额。", -1))
          ])
        ]),
        _createElementVNode("div", _hoisted_7, [
          _cache[26] || (_cache[26] = _createElementVNode("label", {
            class: "field-label",
            for: "rapid-after-upload"
          }, "上传完成后处理", -1)),
          _createVNode(_component_v_select, {
            id: "rapid-after-upload",
            modelValue: afterUpload.value,
            "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((afterUpload).value = $event)),
            items: [{ title: '保留硬链接文件', value: 'keep' }, { title: '删除硬链接文件', value: 'delete' }, { title: '删除硬链接文件及空的父文件夹', value: 'delete_empty' }],
            "aria-label": "上传完成后处理",
            variant: "outlined",
            density: "compact",
            "hide-details": ""
          }, null, 8, ["modelValue"]),
          _cache[27] || (_cache[27] = _createElementVNode("p", { class: "field-help" }, "仅在115上传成功后删除。清理空父文件夹时遇到非空目录即停止，保留整理根目录。", -1))
        ]),
        _cache[28] || (_cache[28] = _createElementVNode("div", { class: "config-note" }, "先在 MP 存储设置中授权115。停用插件会暂停队列。", -1))
      ], 512), [
        [_vShow, tab.value === 'general']
      ]),
      _withDirectives(_createElementVNode("section", _hoisted_8, [
        (directoryError.value)
          ? (_openBlock(), _createBlock(_component_v_alert, {
              key: 0,
              type: "error",
              variant: "tonal",
              density: "compact"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(directoryError.value) + " ", 1),
                _createVNode(_component_v_btn, {
                  variant: "text",
                  size: "small",
                  onClick: loadDirectories
                }, {
                  default: _withCtx(() => [...(_cache[29] || (_cache[29] = [
                    _createTextVNode("重新读取", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            }))
          : (!loading.value && !directories.value.length)
            ? (_openBlock(), _createElementBlock("p", _hoisted_9, "没有可用的本地整理目标，请先在 MP 设置 → 目录管理中配置本地媒体库目录。"))
            : _createCommentVNode("", true),
        _createElementVNode("div", _hoisted_10, [
          (config.mappings.length)
            ? (_openBlock(), _createBlock(_component_v_select, {
                key: 0,
                modelValue: mappingIndex.value,
                "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((mappingIndex).value = $event)),
                items: mappingOptions.value,
                "aria-label": "选择目录映射",
                variant: "outlined",
                density: "compact",
                "hide-details": "",
                class: "mapping-select"
              }, null, 8, ["modelValue", "items"]))
            : (_openBlock(), _createElementBlock("span", _hoisted_11, "尚未配置目录映射")),
          _createVNode(_component_v_btn, {
            variant: "tonal",
            color: "primary",
            size: "small",
            onClick: addMapping
          }, {
            default: _withCtx(() => [...(_cache[30] || (_cache[30] = [
              _createTextVNode("添加映射", -1)
            ]))]),
            _: 1
          })
        ]),
        (mapping.value)
          ? (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
              _createElementVNode("div", _hoisted_12, [
                _cache[31] || (_cache[31] = _createElementVNode("label", {
                  class: "field-label",
                  for: "rapid-local"
                }, "MP整理目标目录", -1)),
                _createVNode(_component_v_select, {
                  id: "rapid-local",
                  modelValue: mapping.value.library_root,
                  "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((mapping.value.library_root) = $event)),
                  items: directories.value,
                  "aria-label": "MP整理目标目录",
                  placeholder: "选择目录管理中的本地媒体库",
                  variant: "outlined",
                  density: "compact",
                  "hide-details": ""
                }, null, 8, ["modelValue", "items"]),
                (mapping.value.library_root && !directories.value.some(item => item.value === mapping.value.library_root))
                  ? (_openBlock(), _createElementBlock("p", _hoisted_13, "该目录已不在系统目录管理中，请重新选择。"))
                  : _createCommentVNode("", true),
                _cache[32] || (_cache[32] = _createElementVNode("p", { class: "field-help" }, "来自 MP 设置 → 目录管理，使用“媒体库目录”，不是下载目录。", -1))
              ]),
              _createElementVNode("div", _hoisted_14, [
                _cache[33] || (_cache[33] = _createElementVNode("label", {
                  class: "field-label",
                  for: "rapid-remote"
                }, "115目标根目录", -1)),
                _createVNode(_component_v_text_field, {
                  id: "rapid-remote",
                  modelValue: mapping.value.remote_root,
                  "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((mapping.value.remote_root) = $event)),
                  "aria-label": "115目标根目录",
                  placeholder: "/影视库/电影",
                  variant: "outlined",
                  density: "compact",
                  "hide-details": ""
                }, null, 8, ["modelValue"]),
                _cache[34] || (_cache[34] = _createElementVNode("p", { class: "field-help" }, "填写网盘路径，子目录与文件名原样保留。", -1))
              ]),
              _createElementVNode("div", _hoisted_15, [
                _cache[35] || (_cache[35] = _createElementVNode("label", {
                  class: "field-label",
                  for: "rapid-attempts"
                }, "最大秒传尝试次数", -1)),
                _createVNode(_component_v_text_field, {
                  id: "rapid-attempts",
                  modelValue: mapping.value.max_attempts,
                  "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((mapping.value.max_attempts) = $event)),
                  modelModifiers: { number: true },
                  "aria-label": "最大秒传尝试次数",
                  type: "number",
                  min: "1",
                  max: "1000",
                  variant: "outlined",
                  density: "compact",
                  "hide-details": ""
                }, null, 8, ["modelValue"]),
                _cache[36] || (_cache[36] = _createElementVNode("p", { class: "field-help" }, "仅对本目录生效，默认3次；明确未命中达到上限后普通上传，网络异常不消耗次数。", -1))
              ]),
              _createElementVNode("div", _hoisted_16, [
                _cache[37] || (_cache[37] = _createElementVNode("label", {
                  class: "field-label",
                  for: "rapid-initial-delay"
                }, [
                  _createTextVNode("首次上传前等待（第0次） "),
                  _createElementVNode("span", { class: "field-unit" }, "分钟")
                ], -1)),
                _createVNode(_component_v_text_field, {
                  id: "rapid-initial-delay",
                  modelValue: mapping.value.initial_delay_minutes,
                  "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((mapping.value.initial_delay_minutes) = $event)),
                  modelModifiers: { number: true },
                  "aria-label": "首次上传前等待分钟数",
                  type: "number",
                  min: "0",
                  max: "525600",
                  variant: "outlined",
                  density: "compact",
                  "hide-details": ""
                }, null, 8, ["modelValue"]),
                _cache[38] || (_cache[38] = _createElementVNode("p", { class: "field-help" }, "默认0，入队后立即尝试。首次等待不占并发名额，不计入尝试次数；仅影响新入队文件。", -1))
              ]),
              _createElementVNode("div", _hoisted_17, [
                _cache[40] || (_cache[40] = _createElementVNode("div", { class: "field-label" }, [
                  _createTextVNode("失败后的等待时间 "),
                  _createElementVNode("span", { class: "field-unit" }, "分钟")
                ], -1)),
                _createElementVNode("div", _hoisted_18, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(mapping.value.retry_minutes, (_, tier) => {
                    return (_openBlock(), _createElementBlock("div", {
                      key: tier,
                      class: "retry-field"
                    }, [
                      _createElementVNode("label", {
                        class: "field-help",
                        for: `rapid-retry-${tier}`
                      }, "第 " + _toDisplayString(tier + 1) + " 次失败后", 9, _hoisted_19),
                      _createElementVNode("div", _hoisted_20, [
                        _createVNode(_component_v_text_field, {
                          id: `rapid-retry-${tier}`,
                          modelValue: mapping.value.retry_minutes[tier],
                          "onUpdate:modelValue": $event => ((mapping.value.retry_minutes[tier]) = $event),
                          modelModifiers: { number: true },
                          "aria-label": `第${tier + 1}次失败后等待分钟数`,
                          type: "number",
                          min: "1",
                          max: "525600",
                          variant: "outlined",
                          density: "compact",
                          "hide-details": ""
                        }, null, 8, ["id", "modelValue", "onUpdate:modelValue", "aria-label"]),
                        _createVNode(_component_v_btn, {
                          icon: "mdi-close",
                          variant: "text",
                          size: "x-small",
                          "aria-label": `删除第${tier + 1}个等待阶段`,
                          disabled: mapping.value.retry_minutes.length <= 1,
                          onClick: $event => (mapping.value.retry_minutes.splice(tier, 1))
                        }, null, 8, ["aria-label", "disabled", "onClick"])
                      ])
                    ]))
                  }), 128))
                ]),
                _createVNode(_component_v_btn, {
                  class: "add-retry",
                  variant: "text",
                  size: "small",
                  color: "primary",
                  onClick: _cache[9] || (_cache[9] = $event => (mapping.value.retry_minutes.push(1440)))
                }, {
                  default: _withCtx(() => [...(_cache[39] || (_cache[39] = [
                    _createTextVNode("＋ 添加等待阶段", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _createElementVNode("div", _hoisted_21, [
                _cache[42] || (_cache[42] = _createElementVNode("p", { class: "field-help" }, "网络异常按末档间隔重试，秒传未命中达到上限后普通上传。", -1)),
                _createVNode(_component_v_btn, {
                  color: "error",
                  variant: "text",
                  size: "small",
                  onClick: removeMapping
                }, {
                  default: _withCtx(() => [...(_cache[41] || (_cache[41] = [
                    _createTextVNode("删除此映射", -1)
                  ]))]),
                  _: 1
                })
              ])
            ], 64))
          : (_openBlock(), _createElementBlock("div", _hoisted_22, "添加一组本地目录与115目录，只有匹配的整理文件才会入队。"))
      ], 512), [
        [_vShow, tab.value === 'mappings']
      ]),
      _withDirectives(_createElementVNode("section", _hoisted_23, [
        _createElementVNode("div", _hoisted_24, [
          _cache[43] || (_cache[43] = _createElementVNode("div", null, [
            _createElementVNode("strong", null, "下载器监控增强"),
            _createElementVNode("p", null, "继续使用 MP 原有的下载器监控与整理流程")
          ], -1)),
          _createVNode(_component_v_switch, {
            modelValue: config.qb_enabled,
            "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((config.qb_enabled) = $event)),
            "aria-label": "下载器监控增强",
            color: "primary",
            density: "compact",
            "hide-details": ""
          }, null, 8, ["modelValue"])
        ]),
        (downloaderError.value)
          ? (_openBlock(), _createBlock(_component_v_alert, {
              key: 0,
              type: "error",
              variant: "tonal",
              density: "compact"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(downloaderError.value) + " ", 1),
                _createVNode(_component_v_btn, {
                  variant: "text",
                  size: "small",
                  onClick: loadDownloaders
                }, {
                  default: _withCtx(() => [...(_cache[44] || (_cache[44] = [
                    _createTextVNode("重新读取", -1)
                  ]))]),
                  _: 1
                })
              ]),
              _: 1
            }))
          : (!loading.value && !downloaders.value.length)
            ? (_openBlock(), _createElementBlock("p", _hoisted_25, "没有可用的 qB 下载器，请先在 MP 设置中添加并启用。"))
            : _createCommentVNode("", true),
        _createElementVNode("div", _hoisted_26, [
          _cache[45] || (_cache[45] = _createElementVNode("label", {
            class: "field-label",
            for: "rapid-downloaders"
          }, "监控的qB下载器", -1)),
          _createVNode(_component_v_select, {
            id: "rapid-downloaders",
            modelValue: config.downloaders,
            "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((config.downloaders) = $event)),
            items: downloaders.value,
            "aria-label": "监控的qB下载器",
            multiple: "",
            chips: "",
            "closable-chips": "",
            clearable: "",
            placeholder: "选择已有下载器，可多选",
            variant: "outlined",
            density: "compact",
            "hide-details": ""
          }, null, 8, ["modelValue", "items"]),
          _cache[46] || (_cache[46] = _createElementVNode("p", { class: "field-help" }, "来自 MP 已启用的 qB 下载器。选择后只监控所选 qB；留空为全部。", -1))
        ]),
        _createElementVNode("div", _hoisted_27, [
          _createElementVNode("div", _hoisted_28, [
            _cache[47] || (_cache[47] = _createElementVNode("label", {
              class: "field-label",
              for: "rapid-include"
            }, "标签白名单", -1)),
            _createVNode(_component_v_combobox, {
              id: "rapid-include",
              modelValue: config.include_tags,
              "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((config.include_tags) = $event)),
              "aria-label": "标签白名单",
              multiple: "",
              chips: "",
              "closable-chips": "",
              variant: "outlined",
              density: "compact",
              "hide-details": ""
            }, null, 8, ["modelValue"]),
            _cache[48] || (_cache[48] = _createElementVNode("p", { class: "field-help" }, "命中任一白名单标签即可。", -1))
          ]),
          _createElementVNode("div", _hoisted_29, [
            _cache[49] || (_cache[49] = _createElementVNode("label", {
              class: "field-label",
              for: "rapid-exclude"
            }, "标签黑名单", -1)),
            _createVNode(_component_v_combobox, {
              id: "rapid-exclude",
              modelValue: config.exclude_tags,
              "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((config.exclude_tags) = $event)),
              "aria-label": "标签黑名单",
              multiple: "",
              chips: "",
              "closable-chips": "",
              variant: "outlined",
              density: "compact",
              "hide-details": ""
            }, null, 8, ["modelValue"]),
            _cache[50] || (_cache[50] = _createElementVNode("p", { class: "field-help" }, "黑名单优先，例如已整理、BDMV。", -1))
          ])
        ]),
        _cache[51] || (_cache[51] = _createElementVNode("div", { class: "config-note" }, [
          _createTextVNode("未整理 → 已整理 → 已上传"),
          _createElementVNode("br"),
          _createTextVNode("MP确认已整理后移除未整理；整个种子全部选中文件上传完成后添加已上传。普通下载列表、按Hash查询及其他类型下载器不受选择限制。使用前请停用独立的qB标签监控插件。")
        ], -1))
      ], 512), [
        [_vShow, tab.value === 'qb']
      ]),
      _withDirectives(_createElementVNode("section", _hoisted_30, [
        _createElementVNode("div", _hoisted_31, [
          _cache[52] || (_cache[52] = _createElementVNode("div", null, [
            _createElementVNode("strong", null, "BDMV 整目录上传"),
            _createElementVNode("p", null, "定时扫描已完成且同时带有 BDMV、未整理标签的种子")
          ], -1)),
          _createVNode(_component_v_switch, {
            modelValue: config.bdmv.enabled,
            "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((config.bdmv.enabled) = $event)),
            "aria-label": "启用BDMV上传",
            color: "primary",
            "hide-details": ""
          }, null, 8, ["modelValue"])
        ]),
        _createElementVNode("div", _hoisted_32, [
          _createElementVNode("div", _hoisted_33, [
            _cache[53] || (_cache[53] = _createElementVNode("label", {
              class: "field-label",
              for: "bdmv-time"
            }, "扫描周期（Cron）", -1)),
            _createVNode(_component_v_text_field, {
              id: "bdmv-time",
              modelValue: config.bdmv.cron,
              "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((config.bdmv.cron) = $event)),
              placeholder: "0 2 * * *",
              "aria-label": "扫描周期（Cron）",
              variant: "outlined",
              density: "compact",
              "hide-details": ""
            }, null, 8, ["modelValue"]),
            _cache[54] || (_cache[54] = _createElementVNode("p", { class: "field-help" }, "分 时 日 月 周，空格分隔。默认 0 2 * * *（每天02:00）；*/30 * * * * 为每30分钟。使用 MP 时区，周建议填 mon–sun。", -1))
          ]),
          _createElementVNode("div", _hoisted_34, [
            _cache[55] || (_cache[55] = _createElementVNode("label", {
              class: "field-label",
              for: "bdmv-plugin"
            }, "CloudDrive2储存插件 ID", -1)),
            _createVNode(_component_v_text_field, {
              id: "bdmv-plugin",
              modelValue: config.bdmv.cd2_plugin_id,
              "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((config.bdmv.cd2_plugin_id) = $event)),
              "aria-label": "CloudDrive2储存插件ID",
              variant: "outlined",
              density: "compact",
              "hide-details": ""
            }, null, 8, ["modelValue"]),
            _cache[56] || (_cache[56] = _createElementVNode("p", { class: "field-help" }, "默认 CloudDriveDisk，复用其连接。", -1))
          ])
        ]),
        _createElementVNode("div", _hoisted_35, [
          _cache[57] || (_cache[57] = _createElementVNode("label", {
            class: "field-label",
            for: "bdmv-downloaders"
          }, "扫描的 qB 下载器", -1)),
          _createVNode(_component_v_select, {
            id: "bdmv-downloaders",
            modelValue: config.bdmv.downloaders,
            "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((config.bdmv.downloaders) = $event)),
            items: downloaders.value,
            "aria-label": "BDMV下载器",
            multiple: "",
            chips: "",
            "closable-chips": "",
            variant: "outlined",
            density: "compact",
            "hide-details": ""
          }, null, 8, ["modelValue", "items"]),
          _cache[58] || (_cache[58] = _createElementVNode("p", { class: "field-help" }, "必须选择；独立于普通整理的标签黑名单。", -1))
        ]),
        _createElementVNode("div", _hoisted_36, [
          (config.bdmv.mappings.length)
            ? (_openBlock(), _createBlock(_component_v_select, {
                key: 0,
                modelValue: bdmvMappingIndex.value,
                "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((bdmvMappingIndex).value = $event)),
                items: bdmvMappingOptions.value,
                "aria-label": "选择BDMV映射",
                variant: "outlined",
                density: "compact",
                "hide-details": "",
                class: "mapping-select"
              }, null, 8, ["modelValue", "items"]))
            : (_openBlock(), _createElementBlock("span", _hoisted_37, "尚未配置 BDMV 映射")),
          _createVNode(_component_v_btn, {
            size: "small",
            variant: "tonal",
            color: "primary",
            onClick: addBdmvMapping
          }, {
            default: _withCtx(() => [...(_cache[59] || (_cache[59] = [
              _createTextVNode("添加映射", -1)
            ]))]),
            _: 1
          })
        ]),
        (bdmvMapping.value)
          ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
              (_openBlock(), _createElementBlock(_Fragment, null, _renderList(bdmvFields, (field) => {
                return _createElementVNode("div", {
                  key: field.key,
                  class: "config-field"
                }, [
                  _createElementVNode("label", {
                    class: "field-label",
                    for: `bdmv-${field.key}`
                  }, _toDisplayString(field.title), 9, _hoisted_38),
                  _createVNode(_component_v_text_field, {
                    id: `bdmv-${field.key}`,
                    modelValue: bdmvMapping.value[field.key],
                    "onUpdate:modelValue": $event => ((bdmvMapping.value[field.key]) = $event),
                    "aria-label": field.title,
                    placeholder: field.example,
                    variant: "outlined",
                    density: "compact",
                    "hide-details": ""
                  }, null, 8, ["id", "modelValue", "onUpdate:modelValue", "aria-label", "placeholder"]),
                  _createElementVNode("p", _hoisted_39, _toDisplayString(field.help), 1)
                ])
              }), 64)),
              _createVNode(_component_v_btn, {
                color: "error",
                variant: "text",
                size: "small",
                class: "align-self-end",
                onClick: removeBdmvMapping
              }, {
                default: _withCtx(() => [...(_cache[60] || (_cache[60] = [
                  _createTextVNode("删除此映射", -1)
                ]))]),
                _: 1
              })
            ], 64))
          : _createCommentVNode("", true),
        _cache[61] || (_cache[61] = _createElementVNode("div", { class: "config-note" }, "CD2 必须已添加本地存储，并能看到下载目录。整目录上传核验完成后添加已上传、移除未整理，保留 BDMV。始终保留本地文件做种。", -1))
      ], 512), [
        [_vShow, tab.value === 'bdmv']
      ])
    ], 8, _hoisted_2),
    _createElementVNode("footer", _hoisted_40, [
      _cache[64] || (_cache[64] = _createElementVNode("span", { class: "footer-hint" }, "切换分页保留未保存内容", -1)),
      _createVNode(_component_v_btn, {
        variant: "text",
        disabled: saving.value,
        onClick: _cache[19] || (_cache[19] = $event => (emit('close')))
      }, {
        default: _withCtx(() => [...(_cache[62] || (_cache[62] = [
          _createTextVNode("关闭", -1)
        ]))]),
        _: 1
      }, 8, ["disabled"]),
      _createVNode(_component_v_btn, {
        color: "primary",
        variant: "flat",
        disabled: loading.value || loadFailed.value,
        loading: saving.value,
        onClick: save
      }, {
        default: _withCtx(() => [...(_cache[63] || (_cache[63] = [
          _createTextVNode("保存配置", -1)
        ]))]),
        _: 1
      }, 8, ["disabled", "loading"])
    ])
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-0e037439"]]);

export { Config as default };
