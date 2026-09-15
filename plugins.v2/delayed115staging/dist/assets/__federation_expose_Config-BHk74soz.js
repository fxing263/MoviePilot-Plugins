import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { P as PLUGIN_ID, n as normalizeConfig, v as validateAndSave } from './shared-DZMfIF0M.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createVNode:_createVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "pa-4" };
const _hoisted_2 = ["disabled"];
const _hoisted_3 = { class: "d-flex align-center mb-3" };
const _hoisted_4 = { class: "d-flex align-center mb-2" };
const _hoisted_5 = {
  key: 1,
  class: "pt-4"
};
const _hoisted_6 = { class: "d-flex flex-wrap ga-2 mb-4" };
const _hoisted_7 = { class: "d-flex flex-wrap ga-2 mt-4" };

const {onMounted,reactive,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: [Object, Function], default: () => ({}) },
  pluginId: { type: String, default: PLUGIN_ID },
},
  emits: ['save', 'close', 'switch'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const config = reactive(normalizeConfig(props.initialConfig));
const loading = ref(true);
const loadFailed = ref(false);
const saving = ref(false);
const error = ref('');

function addTier(rule) {
  const previous = rule.tiers[rule.tiers.length - 2]?.below_gb || 0;
  rule.tiers.splice(rule.tiers.length - 1, 0, { below_gb: Number(previous) + 5, delay_minutes: 30 });
}

async function save() {
  if (loading.value || loadFailed.value || saving.value) return
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
  } catch (failure) {
    loadFailed.value = true;
    error.value = `读取配置失败，请重新打开配置页：${failure?.message || failure}`;
  } finally {
    loading.value = false;
  }
});

return (_ctx, _cache) => {
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_progress_linear = _resolveComponent("v-progress-linear");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_col = _resolveComponent("v-col");
  const _component_v_row = _resolveComponent("v-row");
  const _component_v_card = _resolveComponent("v-card");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _cache[23] || (_cache[23] = _createElementVNode("div", { class: "text-h6 mb-3" }, "115 延迟暂存配置", -1)),
    (error.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 0,
          type: "error",
          variant: "tonal",
          class: "mb-3"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    (loading.value)
      ? (_openBlock(), _createBlock(_component_v_progress_linear, {
          key: 1,
          indeterminate: "",
          class: "mb-3"
        }))
      : _createCommentVNode("", true),
    _createElementVNode("fieldset", {
      disabled: loading.value || saving.value,
      class: "config-fields"
    }, [
      _createVNode(_component_v_switch, {
        modelValue: config.enabled,
        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((config.enabled) = $event)),
        label: "启用插件",
        color: "primary",
        "hide-details": ""
      }, null, 8, ["modelValue"]),
      _createVNode(_component_v_alert, {
        type: "info",
        variant: "tonal",
        class: "my-4"
      }, {
        default: _withCtx(() => [...(_cache[8] || (_cache[8] = [
          _createTextVNode(" 每个整理目录分别设置暂存目录与延迟规则，例如 /pt1 → /115-staging1，/pt2 → /115-staging2。 各整理目录之间、各暂存目录之间均不能相同或互为父子目录；整理目录与任一暂存目录也不能重叠。 新配置只用于新任务，已登记任务保留当时的延迟、路径、确认方式与清理选项。 ", -1)
        ]))]),
        _: 1
      }),
      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(config.mappings, (mapping, mappingIndex) => {
        return (_openBlock(), _createBlock(_component_v_card, {
          key: mappingIndex,
          variant: "outlined",
          class: "mb-4 pa-3"
        }, {
          default: _withCtx(() => [
            _createElementVNode("div", _hoisted_3, [
              _createElementVNode("strong", null, "目录映射 " + _toDisplayString(mappingIndex + 1), 1),
              _createVNode(_component_v_spacer),
              _createVNode(_component_v_btn, {
                variant: "text",
                color: "error",
                size: "small",
                onClick: $event => (config.mappings.splice(mappingIndex, 1))
              }, {
                default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
                  _createTextVNode("删除映射", -1)
                ]))]),
                _: 1
              }, 8, ["onClick"])
            ]),
            _createVNode(_component_v_text_field, {
              modelValue: mapping.library_root,
              "onUpdate:modelValue": $event => ((mapping.library_root) = $event),
              label: "整理媒体库根目录",
              placeholder: `/pt${mappingIndex + 1}`,
              hint: "从此根目录计算相对路径，保留分类、剧名、季等完整目录结构。",
              "persistent-hint": "",
              class: "mb-3"
            }, null, 8, ["modelValue", "onUpdate:modelValue", "placeholder"]),
            _createVNode(_component_v_text_field, {
              modelValue: mapping.staging_root,
              "onUpdate:modelValue": $event => ((mapping.staging_root) = $event),
              label: "对应的 115 监控暂存目录",
              placeholder: `/115-staging${mappingIndex + 1}`,
              hint: "必须与对应源文件处于同一文件系统；不支持硬链接时任务失败，不复制数据。",
              "persistent-hint": "",
              class: "mb-3"
            }, null, 8, ["modelValue", "onUpdate:modelValue", "placeholder"]),
            _createVNode(_component_v_alert, {
              type: "info",
              variant: "tonal",
              class: "mb-3"
            }, {
              default: _withCtx(() => [...(_cache[10] || (_cache[10] = [
                _createTextVNode(" 规则目录相对于本组整理根目录，例如 /国产电视剧。填写 / 表示整个根目录，此时不能再添加子目录规则。 同组规则不能相同或互为父子目录；未匹配文件不处理。大小使用十进制 GB（1 GB = 1,000,000,000 字节），上限不含、下限包含。 ", -1)
              ]))]),
              _: 1
            }),
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(mapping.rules, (rule, index) => {
              return (_openBlock(), _createBlock(_component_v_card, {
                key: index,
                variant: "outlined",
                class: "mb-3 pa-3"
              }, {
                default: _withCtx(() => [
                  _createElementVNode("div", _hoisted_4, [
                    _createElementVNode("strong", null, _toDisplayString(Array.isArray(rule.tiers) ? '按大小延迟' : '固定延迟') + " · 规则 " + _toDisplayString(index + 1), 1),
                    _createVNode(_component_v_spacer),
                    _createVNode(_component_v_btn, {
                      variant: "text",
                      color: "error",
                      size: "small",
                      onClick: $event => (mapping.rules.splice(index, 1))
                    }, {
                      default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
                        _createTextVNode("删除规则", -1)
                      ]))]),
                      _: 1
                    }, 8, ["onClick"])
                  ]),
                  _createVNode(_component_v_text_field, {
                    modelValue: rule.directory,
                    "onUpdate:modelValue": $event => ((rule.directory) = $event),
                    label: "规则目录（相对于媒体库）",
                    placeholder: "/国产电视剧"
                  }, null, 8, ["modelValue", "onUpdate:modelValue"]),
                  (!Array.isArray(rule.tiers))
                    ? (_openBlock(), _createBlock(_component_v_text_field, {
                        key: 0,
                        modelValue: rule.delay_minutes,
                        "onUpdate:modelValue": $event => ((rule.delay_minutes) = $event),
                        modelModifiers: { number: true },
                        type: "number",
                        min: "0",
                        label: "延迟（分钟）"
                      }, null, 8, ["modelValue", "onUpdate:modelValue"]))
                    : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(rule.tiers, (tier, tierIndex) => {
                          return (_openBlock(), _createBlock(_component_v_row, {
                            key: tierIndex,
                            dense: ""
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_v_col, {
                                cols: "12",
                                sm: "6"
                              }, {
                                default: _withCtx(() => [
                                  (tierIndex < rule.tiers.length - 1)
                                    ? (_openBlock(), _createBlock(_component_v_text_field, {
                                        key: 0,
                                        modelValue: tier.below_gb,
                                        "onUpdate:modelValue": $event => ((tier.below_gb) = $event),
                                        modelModifiers: { number: true },
                                        type: "number",
                                        min: "0",
                                        label: "本档上限 GB（不含）",
                                        prefix: tierIndex ? `≥ ${rule.tiers[tierIndex - 1].below_gb}，<` : '<'
                                      }, null, 8, ["modelValue", "onUpdate:modelValue", "prefix"]))
                                    : (_openBlock(), _createElementBlock("div", _hoisted_5, _toDisplayString(tierIndex ? `≥ ${rule.tiers[tierIndex - 1].below_gb} GB` : '所有大小'), 1))
                                ]),
                                _: 2
                              }, 1024),
                              _createVNode(_component_v_col, {
                                cols: "9",
                                sm: "4"
                              }, {
                                default: _withCtx(() => [
                                  _createVNode(_component_v_text_field, {
                                    modelValue: tier.delay_minutes,
                                    "onUpdate:modelValue": $event => ((tier.delay_minutes) = $event),
                                    modelModifiers: { number: true },
                                    type: "number",
                                    min: "0",
                                    label: "延迟（分钟）"
                                  }, null, 8, ["modelValue", "onUpdate:modelValue"])
                                ]),
                                _: 2
                              }, 1024),
                              _createVNode(_component_v_col, {
                                cols: "3",
                                sm: "2"
                              }, {
                                default: _withCtx(() => [
                                  (tierIndex < rule.tiers.length - 1)
                                    ? (_openBlock(), _createBlock(_component_v_btn, {
                                        key: 0,
                                        variant: "text",
                                        color: "error",
                                        onClick: $event => (rule.tiers.splice(tierIndex, 1))
                                      }, {
                                        default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
                                          _createTextVNode("删除", -1)
                                        ]))]),
                                        _: 1
                                      }, 8, ["onClick"]))
                                    : _createCommentVNode("", true)
                                ]),
                                _: 2
                              }, 1024)
                            ]),
                            _: 2
                          }, 1024))
                        }), 128)),
                        _createVNode(_component_v_btn, {
                          variant: "tonal",
                          size: "small",
                          onClick: $event => (addTier(rule))
                        }, {
                          default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                            _createTextVNode("新增大小分档", -1)
                          ]))]),
                          _: 1
                        }, 8, ["onClick"])
                      ], 64))
                ]),
                _: 2
              }, 1024))
            }), 128)),
            _createElementVNode("div", _hoisted_6, [
              _createVNode(_component_v_btn, {
                variant: "tonal",
                onClick: $event => (mapping.rules.push({ directory: '', delay_minutes: 60 }))
              }, {
                default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                  _createTextVNode("新增固定延迟规则", -1)
                ]))]),
                _: 1
              }, 8, ["onClick"]),
              _createVNode(_component_v_btn, {
                variant: "tonal",
                onClick: $event => (mapping.rules.push({ directory: '', tiers: [{ below_gb: 5, delay_minutes: 10 }, { below_gb: 20, delay_minutes: 30 }, { below_gb: null, delay_minutes: 60 }] }))
              }, {
                default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                  _createTextVNode("新增大小延迟规则", -1)
                ]))]),
                _: 1
              }, 8, ["onClick"])
            ])
          ]),
          _: 2
        }, 1024))
      }), 128)),
      _createVNode(_component_v_btn, {
        variant: "tonal",
        class: "mb-4",
        onClick: _cache[1] || (_cache[1] = $event => (config.mappings.push({ library_root: '', staging_root: '', rules: [{ directory: '/', delay_minutes: 60 }] })))
      }, {
        default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
          _createTextVNode("新增整理目录映射", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_v_alert, {
        type: "info",
        variant: "tonal",
        class: "mb-3"
      }, {
        default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
          _createTextVNode("上传器成功后删除暂存文件，插件自动复查并清理对应整理文件，无需手动确认。实际操作和异常请查看插件日志。", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_v_switch, {
        modelValue: config.scan_once,
        "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((config.scan_once) = $event)),
        label: "进行一次全量硬链接",
        color: "warning",
        "hide-details": ""
      }, null, 8, ["modelValue"]),
      _createVNode(_component_v_alert, {
        type: "info",
        variant: "tonal",
        class: "my-3"
      }, {
        default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
          _createTextVNode("启用插件后执行一次：扫描整理目录内匹配规则的普通文件（含字幕、刮削文件），新任务不等待延迟。已有任务不重复创建，扫描成功后自动关闭此选项。中断后重新扫描并去重。", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_v_text_field, {
        modelValue: config.history_days,
        "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.history_days) = $event)),
        modelModifiers: { number: true },
        type: "number",
        min: "1",
        max: "3650",
        label: "已完成任务记录保留天数",
        hint: "默认 7 天，每天清理一次。仅删除记录，失败和未完成任务保留；记录过期后再次手动全量扫描可能重新投递仍保留的整理文件。",
        "persistent-hint": "",
        class: "my-3"
      }, null, 8, ["modelValue"]),
      _createVNode(_component_v_switch, {
        modelValue: config.cleanup_organized,
        "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.cleanup_organized) = $event)),
        label: "确认上传成功后，删除对应的整理硬链接",
        color: "warning",
        "hide-details": ""
      }, null, 8, ["modelValue"]),
      _createVNode(_component_v_switch, {
        modelValue: config.cleanup_empty_dirs,
        "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.cleanup_empty_dirs) = $event)),
        label: "清理空目录（保留媒体库及暂存根目录）",
        color: "primary",
        "hide-details": ""
      }, null, 8, ["modelValue"]),
      _createVNode(_component_v_alert, {
        type: "info",
        variant: "tonal",
        class: "my-3"
      }, {
        default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
          _createTextVNode("插件不上传、不刷新媒体库。下载器源文件与做种清理由现有流程负责。", -1)
        ]))]),
        _: 1
      })
    ], 8, _hoisted_2),
    _createElementVNode("div", _hoisted_7, [
      _createVNode(_component_v_btn, {
        variant: "text",
        onClick: _cache[6] || (_cache[6] = $event => (emit('switch')))
      }, {
        default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
          _createTextVNode("任务列表", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_v_spacer),
      _createVNode(_component_v_btn, {
        variant: "text",
        onClick: _cache[7] || (_cache[7] = $event => (emit('close')))
      }, {
        default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
          _createTextVNode("关闭", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_v_btn, {
        color: "primary",
        disabled: loading.value || loadFailed.value,
        loading: saving.value,
        onClick: save
      }, {
        default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
          _createTextVNode("验证并保存", -1)
        ]))]),
        _: 1
      }, 8, ["disabled", "loading"])
    ])
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-15bee2df"]]);

export { Config as default };
