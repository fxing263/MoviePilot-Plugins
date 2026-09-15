import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc, P as PLUGIN_ID, S as STATE_LABELS, f as formatTime } from './_plugin-vue_export-helper-BzYaA2YH.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,createTextVNode:_createTextVNode,withCtx:_withCtx,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,unref:_unref} = await importShared('vue');


const _hoisted_1 = { class: "pa-4" };
const _hoisted_2 = { class: "d-flex align-center ga-2 mb-3" };
const _hoisted_3 = { class: "path-cell" };
const _hoisted_4 = { class: "text-caption" };
const _hoisted_5 = { class: "text-caption" };
const _hoisted_6 = {
  key: 0,
  class: "text-error"
};
const _hoisted_7 = { class: "text-caption" };
const _hoisted_8 = { class: "path-cell text-caption" };
const _hoisted_9 = { class: "d-flex flex-wrap ga-1 py-2" };
const _hoisted_10 = { key: 0 };
const _hoisted_11 = {
  colspan: "4",
  class: "text-center pa-6"
};
const _hoisted_12 = { class: "text-caption mt-2" };
const _hoisted_13 = { class: "d-flex mt-4" };
const _hoisted_14 = { class: "path-cell mb-3" };

const {computed,onMounted,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: { api: { type: [Object, Function], default: () => ({}) }, pluginId: { type: String, default: PLUGIN_ID } },
  emits: ['switch', 'action', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const tasks = ref([]);
const keyword = ref('');
const page = ref(1);
const loading = ref(false);
const busy = ref('');
const message = ref('');
const messageType = ref('info');
const runtimeError = ref('');
const confirmationMode = ref('manual');
const confirmOpen = ref(false);
const confirming = ref(null);
const remoteReference = ref('');
const verified = ref(false);
const filteredTasks = computed(() => tasks.value.filter(task => `${task.library_root || ''} ${task.relative_path} ${task.staging_path} ${task.id}`.includes(keyword.value || '')));
const pageCount = computed(() => Math.max(1, Math.ceil(filteredTasks.value.length / 20)));
const visibleTasks = computed(() => filteredTasks.value.slice((page.value - 1) * 20, page.value * 20));

function resultText(value) {
  if (value?.method === 'staging_deleted' && value.confirmed === true) return '暂存文件已删除，按上传器约定确认（未查询远端）'
  return value ? (typeof value === 'string' ? value : JSON.stringify(value)) : '—'
}

async function refresh() {
  loading.value = true;
  try {
    const response = await props.api.get(`plugin/${props.pluginId || PLUGIN_ID}/tasks`);
    if (response?.success !== true) throw new Error(response?.message || '读取任务失败')
    tasks.value = response.data?.tasks || [];
    runtimeError.value = response.data?.error || '';
    confirmationMode.value = response.data?.confirmation_mode || 'manual';
    page.value = Math.min(page.value, pageCount.value);
  } catch (failure) {
    messageType.value = 'error';
    message.value = failure?.message || String(failure);
  } finally {
    loading.value = false;
  }
}

/** 操作结果只来自后端，接口失败时不改变本地任务状态。 */
async function action(task, operation, extra = {}) {
  if (busy.value) return false
  busy.value = task.id;
  try {
    const response = await props.api.post(`plugin/${props.pluginId || PLUGIN_ID}/task`, { task_id: task.id, action: operation, ...extra });
    if (response?.success !== true) throw new Error(response?.message || '操作失败')
    messageType.value = 'success';
    message.value = response.message || '操作成功';
    emit('action', { type: operation, data: response });
    await refresh();
    return true
  } catch (failure) {
    messageType.value = 'error';
    message.value = failure?.message || String(failure);
    return false
  } finally {
    busy.value = '';
  }
}

function openConfirmation(task) {
  confirming.value = task;
  remoteReference.value = '';
  verified.value = false;
  confirmOpen.value = true;
}

/** 必须逐任务明确核验远端，打开弹窗及暂存完成都不能自动确认。 */
async function confirmUpload() {
  if (!confirming.value || !verified.value || !remoteReference.value.trim()) return
  if (await action(confirming.value, 'confirm', { verified: true, remote_reference: remoteReference.value.trim() })) confirmOpen.value = false;
}

onMounted(refresh);

return (_ctx, _cache) => {
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_table = _resolveComponent("v-table");
  const _component_v_pagination = _resolveComponent("v-pagination");
  const _component_v_checkbox = _resolveComponent("v-checkbox");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card_actions = _resolveComponent("v-card-actions");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_dialog = _resolveComponent("v-dialog");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _cache[10] || (_cache[10] = _createElementVNode("div", { class: "text-h6" }, "115 延迟暂存任务", -1)),
      _createVNode(_component_v_spacer),
      _createVNode(_component_v_btn, {
        variant: "tonal",
        loading: loading.value,
        disabled: Boolean(busy.value),
        onClick: refresh
      }, {
        default: _withCtx(() => [...(_cache[9] || (_cache[9] = [
          _createTextVNode("刷新", -1)
        ]))]),
        _: 1
      }, 8, ["loading", "disabled"])
    ]),
    (message.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 0,
          type: messageType.value,
          variant: "tonal",
          class: "mb-3"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(message.value), 1)
          ]),
          _: 1
        }, 8, ["type"]))
      : _createCommentVNode("", true),
    (runtimeError.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 1,
          type: "error",
          variant: "tonal",
          class: "mb-3"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(runtimeError.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    _createVNode(_component_v_alert, {
      type: "info",
      variant: "tonal",
      class: "mb-3"
    }, {
      default: _withCtx(() => [
        _createTextVNode(" 新任务确认方式：" + _toDisplayString(confirmationMode.value === 'staging_deleted' ? '上传器删除暂存文件后自动确认' : '手动确认 / 上传器成功回执') + "。每条任务保留登记时的确认方式。 “已暂存”只表示硬链接已交给监控目录；取消任务保留已暂存文件，不能停止外部监控上传器。 ", 1)
      ]),
      _: 1
    }),
    _createVNode(_component_v_text_field, {
      modelValue: keyword.value,
      "onUpdate:modelValue": [
        _cache[0] || (_cache[0] = $event => ((keyword).value = $event)),
        _cache[1] || (_cache[1] = $event => (page.value = 1))
      ],
      label: "搜索整理根目录、媒体路径、暂存路径或任务 ID",
      clearable: ""
    }, null, 8, ["modelValue"]),
    _createVNode(_component_v_table, { density: "compact" }, {
      default: _withCtx(() => [
        _cache[14] || (_cache[14] = _createElementVNode("thead", null, [
          _createElementVNode("tr", null, [
            _createElementVNode("th", null, "媒体路径 / 任务 ID"),
            _createElementVNode("th", null, "状态 / 可暂存时间"),
            _createElementVNode("th", null, "上传 / 清理结果"),
            _createElementVNode("th", null, "操作")
          ])
        ], -1)),
        _createElementVNode("tbody", null, [
          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(visibleTasks.value, (task) => {
            return (_openBlock(), _createElementBlock("tr", {
              key: task.id
            }, [
              _createElementVNode("td", _hoisted_3, [
                _createElementVNode("div", null, _toDisplayString(task.relative_path), 1),
                _createElementVNode("div", _hoisted_4, "整理根目录：" + _toDisplayString(task.library_root || '—'), 1),
                _createElementVNode("div", _hoisted_5, "暂存路径：" + _toDisplayString(task.staging_path), 1),
                _createElementVNode("small", null, _toDisplayString(task.id), 1),
                (task.error)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_6, _toDisplayString(task.error), 1))
                  : _createCommentVNode("", true)
              ]),
              _createElementVNode("td", null, [
                _createVNode(_component_v_chip, {
                  size: "small",
                  class: "my-1"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(_unref(STATE_LABELS)[task.state] || task.state), 1)
                  ]),
                  _: 2
                }, 1024),
                _createElementVNode("div", _hoisted_7, _toDisplayString(_unref(formatTime)(task.ready_at)), 1)
              ]),
              _createElementVNode("td", _hoisted_8, [
                _createElementVNode("div", null, "确认方式：" + _toDisplayString(task.confirmation_mode === 'staging_deleted' ? '暂存文件删除后自动确认' : '手动 / 成功回执'), 1),
                _createElementVNode("div", null, "上传：" + _toDisplayString(resultText(task.upload_result)), 1),
                _createElementVNode("div", null, "清理：" + _toDisplayString(resultText(task.cleanup_result)), 1)
              ]),
              _createElementVNode("td", null, [
                _createElementVNode("div", _hoisted_9, [
                  (['failed', 'cleanup_failed'].includes(task.state))
                    ? (_openBlock(), _createBlock(_component_v_btn, {
                        key: 0,
                        size: "small",
                        variant: "tonal",
                        disabled: Boolean(busy.value),
                        onClick: $event => (action(task, 'retry'))
                      }, {
                        default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
                          _createTextVNode("重试", -1)
                        ]))]),
                        _: 1
                      }, 8, ["disabled", "onClick"]))
                    : _createCommentVNode("", true),
                  (['waiting', 'failed', 'staged', 'linking'].includes(task.state))
                    ? (_openBlock(), _createBlock(_component_v_btn, {
                        key: 1,
                        size: "small",
                        variant: "text",
                        disabled: Boolean(busy.value),
                        onClick: $event => (action(task, 'cancel'))
                      }, {
                        default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
                          _createTextVNode("取消", -1)
                        ]))]),
                        _: 1
                      }, 8, ["disabled", "onClick"]))
                    : _createCommentVNode("", true),
                  (task.state === 'staged')
                    ? (_openBlock(), _createBlock(_component_v_btn, {
                        key: 2,
                        size: "small",
                        variant: "tonal",
                        color: "warning",
                        disabled: Boolean(busy.value),
                        onClick: $event => (openConfirmation(task))
                      }, {
                        default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                          _createTextVNode("确认上传并清理", -1)
                        ]))]),
                        _: 1
                      }, 8, ["disabled", "onClick"]))
                    : _createCommentVNode("", true)
                ])
              ])
            ]))
          }), 128)),
          (!visibleTasks.value.length)
            ? (_openBlock(), _createElementBlock("tr", _hoisted_10, [
                _createElementVNode("td", _hoisted_11, _toDisplayString(loading.value ? '正在加载…' : '暂无匹配任务'), 1)
              ]))
            : _createCommentVNode("", true)
        ])
      ]),
      _: 1
    }),
    (pageCount.value > 1)
      ? (_openBlock(), _createBlock(_component_v_pagination, {
          key: 2,
          modelValue: page.value,
          "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((page).value = $event)),
          length: pageCount.value,
          "total-visible": 5
        }, null, 8, ["modelValue", "length"]))
      : _createCommentVNode("", true),
    _createElementVNode("div", _hoisted_12, "共 " + _toDisplayString(filteredTasks.value.length) + " 条任务，时间按当前浏览器时区显示。", 1),
    _createElementVNode("div", _hoisted_13, [
      _createVNode(_component_v_btn, {
        variant: "text",
        onClick: _cache[3] || (_cache[3] = $event => (emit('switch')))
      }, {
        default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
          _createTextVNode("配置", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_v_spacer),
      _createVNode(_component_v_btn, {
        variant: "text",
        onClick: _cache[4] || (_cache[4] = $event => (emit('close')))
      }, {
        default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
          _createTextVNode("关闭", -1)
        ]))]),
        _: 1
      })
    ]),
    _createVNode(_component_v_dialog, {
      modelValue: confirmOpen.value,
      "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((confirmOpen).value = $event)),
      "max-width": "580",
      persistent: Boolean(busy.value)
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_card, { title: "确认远端上传成功" }, {
          default: _withCtx(() => [
            _createVNode(_component_v_card_text, null, {
              default: _withCtx(() => [
                _createElementVNode("p", _hoisted_14, [
                  _createTextVNode("整理根目录：" + _toDisplayString(confirming.value?.library_root || '—'), 1),
                  _cache[17] || (_cache[17] = _createElementVNode("br", null, null, -1)),
                  _createTextVNode("媒体：" + _toDisplayString(confirming.value?.relative_path), 1),
                  _cache[18] || (_cache[18] = _createElementVNode("br", null, null, -1)),
                  _createTextVNode("暂存：" + _toDisplayString(confirming.value?.staging_path), 1)
                ]),
                _createVNode(_component_v_alert, {
                  type: "warning",
                  variant: "tonal",
                  class: "mb-3"
                }, {
                  default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                    _createTextVNode("确认后将清理暂存硬链接，并按此任务记录的清理配置处理整理硬链接。请核对远端文件名、大小及目录。", -1)
                  ]))]),
                  _: 1
                }),
                _createVNode(_component_v_text_field, {
                  modelValue: remoteReference.value,
                  "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((remoteReference).value = $event)),
                  label: "远端文件 ID / 路径 / 上传凭据"
                }, null, 8, ["modelValue"]),
                _createVNode(_component_v_checkbox, {
                  modelValue: verified.value,
                  "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((verified).value = $event)),
                  label: "我已在 115 核验该文件上传成功，允许执行此任务的本地清理"
                }, null, 8, ["modelValue"])
              ]),
              _: 1
            }),
            _createVNode(_component_v_card_actions, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_btn, {
                  disabled: Boolean(busy.value),
                  onClick: _cache[7] || (_cache[7] = $event => (confirmOpen.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[20] || (_cache[20] = [
                    _createTextVNode("返回", -1)
                  ]))]),
                  _: 1
                }, 8, ["disabled"]),
                _createVNode(_component_v_spacer),
                _createVNode(_component_v_btn, {
                  color: "warning",
                  loading: Boolean(busy.value),
                  disabled: !verified.value || !remoteReference.value.trim(),
                  onClick: confirmUpload
                }, {
                  default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                    _createTextVNode("确认并清理", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading", "disabled"])
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue", "persistent"])
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-d26a4289"]]);

export { Page as default };
