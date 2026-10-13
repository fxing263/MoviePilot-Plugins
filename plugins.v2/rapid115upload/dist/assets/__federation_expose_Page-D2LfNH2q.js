import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { P as PLUGIN_ID, p as postprocessAction, S as STATE_LABELS, a as POSTPROCESS_LABELS, f as formatTime } from './shared-DMbgpPgW.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,resolveComponent:_resolveComponent,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createVNode:_createVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,unref:_unref} = await importShared('vue');


const _hoisted_1 = {
  key: 0,
  class: "records-page"
};
const _hoisted_2 = { class: "text-success d-flex align-center ga-2" };
const _hoisted_3 = { class: "text-h5 font-weight-bold mt-1" };
const _hoisted_4 = { class: "text-caption text-medium-emphasis" };
const _hoisted_5 = { class: "d-flex flex-wrap ga-2 mt-2" };
const _hoisted_6 = {
  key: 0,
  class: "text-caption text-medium-emphasis mt-2"
};
const _hoisted_7 = { class: "d-flex flex-wrap align-center ga-2" };
const _hoisted_8 = { class: "record-name py-3" };
const _hoisted_9 = { class: "font-weight-medium" };
const _hoisted_10 = ["title"];
const _hoisted_11 = { class: "text-no-wrap" };
const _hoisted_12 = {
  key: 0,
  class: "ml-2"
};
const _hoisted_13 = { key: 0 };
const _hoisted_14 = {
  key: 1,
  class: "text-medium-emphasis"
};
const _hoisted_15 = {
  key: 0,
  class: "task-progress py-2"
};
const _hoisted_16 = { class: "text-caption" };
const _hoisted_17 = {
  key: 0,
  class: "text-caption mt-1 text-no-wrap"
};
const _hoisted_18 = {
  key: 1,
  class: "text-medium-emphasis"
};
const _hoisted_19 = { class: "d-flex align-center flex-wrap ga-2 px-3 py-1" };
const _hoisted_20 = { class: "text-caption" };
const _hoisted_21 = { class: "record-name py-2" };
const _hoisted_22 = { class: "record-path text-medium-emphasis" };
const _hoisted_23 = {
  key: 0,
  class: "record-path mt-1"
};
const _hoisted_24 = { class: "task-progress" };
const _hoisted_25 = { key: 1 };
const _hoisted_26 = { key: 2 };
const _hoisted_27 = {
  key: 3,
  class: "text-medium-emphasis"
};
const _hoisted_28 = { key: 0 };
const _hoisted_29 = {
  key: 1,
  class: "text-error"
};
const _hoisted_30 = {
  key: 5,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_31 = { class: "mb-3" };

const {computed,onMounted,onUnmounted,ref,watch} = await importShared('vue');

const _sfc_main = {
  __name: 'Page',
  props: { api: { type: [Object, Function], default: () => ({}) }, pluginId: { type: String, default: PLUGIN_ID }, navKey: { type: String, default: '' } },
  emits: ['switch', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const bdmv = ref({ tasks: [], error: '' });
const bdmvLabels = { waiting: '等待上传', submitting: '正在提交', unknown: '等待CD2确认', copying: 'CD2上传中', tagging: '正在更新标签', done: '已上传', blocked: '需要处理' };
const bdmvHeaders = [{ title: '种子 / 目标目录', key: 'name' }, { title: '状态', key: 'state' }, { title: '进度', key: 'progress', sortable: false }];
const tasks = ref([]);
const postStats = ref(null);
const loading = ref(false);
const acting = ref(false);
const enabled = ref(false);
const error = ref('');
const query = ref('');
const stateFilter = ref('all');
const page = ref(1);
const pageSize = ref(25);
const detailsOpen = ref(false);
const selectedTask = ref(null);
const actionError = ref('');
const resolutionOpen = ref(false);
const resolution = ref('');
const resolutionTask = ref(null);
const newFilename = ref('');
const postAction = computed(() => postprocessAction(selectedTask.value));
const hasConflict = computed(() => selectedTask.value?.state === 'blocked' && ['size_mismatch', 'directory'].includes(selectedTask.value?.verification?.reason));
const hasSizeConflict = computed(() => hasConflict.value && selectedTask.value?.verification?.reason === 'size_mismatch');
const headers = [
  { title: '文件', key: 'file', sortable: false },
  { title: '大小', key: 'size', sortable: false, width: 110 },
  { title: '下次尝试', key: 'ready', sortable: false },
  { title: '状态', key: 'state', sortable: false },
  { title: '上传后处理', key: 'postprocess', sortable: false },
  { title: '进度 / 速度', key: 'progress', sortable: false, width: 210 },
  { title: '', key: 'actions', sortable: false },
];
const stateOptions = [{ title: '全部状态', value: 'all' }, ...Object.entries(STATE_LABELS).map(([value, title]) => ({ title, value }))];
const summary = computed(() => Object.entries(STATE_LABELS).map(([state, label]) => ({ state, label, count: tasks.value.filter(task => task.state === state).length })).filter(item => item.count));
const filteredTasks = computed(() => tasks.value.filter(task =>
  (stateFilter.value === 'all' || task.state === stateFilter.value) &&
  (!query.value || `${task.remote_path}`.toLowerCase().includes(query.value.trim().toLowerCase()))
));
const pageCount = computed(() => Math.ceil(filteredTasks.value.length / pageSize.value));
const visibleTasks = computed(() => filteredTasks.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value));
watch([query, stateFilter, pageSize], () => { page.value = 1; });
const uploadedCount = computed(() => tasks.value.filter(task => task.state === 'uploaded').length);
const totalBytes = computed(() => tasks.value.reduce((sum, task) => sum + (task.identity?.[2] || 0), 0));
const uploadedBytes = computed(() => tasks.value.filter(task => task.state === 'uploaded').reduce((sum, task) => sum + (task.identity?.[2] || 0), 0));
function formatSize(value) {
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`
}
function percentage(progress) {
  return progress?.total_bytes > 0 ? Math.min(100, Math.max(0, progress.completed_bytes / progress.total_bytes * 100)) : 0
}
function stageLabel(stage) {
  return { hashing: '计算文件哈希', checking: '检查秒传', uploading: '普通上传', verifying: '提交并校验远端文件' }[stage] || '正在处理'
}
function fileName(path) {
  return path?.split('/').pop() || path
}
function openDetails(task) {
  actionError.value = '';
  selectedTask.value = task;
  detailsOpen.value = true;
}
function stateColor(state) {
  if (['blocked'].includes(state)) return 'error'
  if (state === 'uploaded') return 'success'
  if (state === 'waiting' || state === 'running') return 'warning'
  return 'primary'
}
function openResolution(action) {
  resolution.value = action;
  resolutionTask.value = JSON.parse(JSON.stringify(selectedTask.value));
  const name = fileName(selectedTask.value.remote_path);
  const dot = name.lastIndexOf('.');
  newFilename.value = dot > 0 ? `${name.slice(0, dot)} (本地)${name.slice(dot)}` : `${name} (本地)`;
  actionError.value = '';
  resolutionOpen.value = true;
}
async function act(action) {
  acting.value = true;
  actionError.value = '';
  try {
    const conflictAction = ['rename', 'overwrite'].includes(action);
    const task = conflictAction ? resolutionTask.value : selectedTask.value;
    const payload = { task_id: task.id, action };
    if (conflictAction) Object.assign(payload, { verification: task.verification, filename: newFilename.value, confirmed: action === 'overwrite' });
    const response = await props.api.post(`plugin/${props.pluginId || PLUGIN_ID}/task`, payload);
    if (response?.success !== true) throw new Error(response?.message || '操作失败')
    detailsOpen.value = false;
    resolutionOpen.value = false;
    await refresh();
  } catch (failure) { actionError.value = failure?.message || String(failure); }
  finally { acting.value = false; }
}
async function refresh() {
  if (loading.value) return
  loading.value = true;
  error.value = '';
  try {
    const response = await props.api.get(`plugin/${props.pluginId || PLUGIN_ID}/tasks`);
    if (response?.success !== true) throw new Error(response?.message || '读取状态失败')
    tasks.value = response.data?.tasks || [];
    postStats.value = response.data?.postprocess_stats || null;
    bdmv.value = response.data?.bdmv || { tasks: [], error: '' };
    if (page.value > pageCount.value) page.value = Math.max(1, pageCount.value);
    if (selectedTask.value) selectedTask.value = tasks.value.find(task => task.id === selectedTask.value.id) || null;
    enabled.value = response.data?.enabled === true;
    error.value = response.data?.error || '';
  } catch (failure) {
    error.value = failure?.message || String(failure);
  } finally {
    loading.value = false;
  }
}
let refreshTimer;
let idleTicks = 0;
onMounted(() => {
  // 插件卡片入口交给宿主打开配置；只有独立侧栏页查询和轮询上传队列。
  if (!props.navKey) {
    emit('switch');
    return
  }
  refresh();
  refreshTimer = setInterval(() => { if (!document.hidden && (tasks.value.some(task => task.state === 'running') || ++idleTicks >= 5)) { idleTicks = 0; refresh(); } }, 3000);
});
onUnmounted(() => clearInterval(refreshTimer));

return (_ctx, _cache) => {
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_chip = _resolveComponent("v-chip");
  const _component_v_card_text = _resolveComponent("v-card-text");
  const _component_v_card = _resolveComponent("v-card");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_card_item = _resolveComponent("v-card-item");
  const _component_v_progress_linear = _resolveComponent("v-progress-linear");
  const _component_v_data_table_virtual = _resolveComponent("v-data-table-virtual");
  const _component_v_divider = _resolveComponent("v-divider");
  const _component_v_pagination = _resolveComponent("v-pagination");
  const _component_v_card_title = _resolveComponent("v-card-title");
  const _component_v_data_table = _resolveComponent("v-data-table");
  const _component_v_card_actions = _resolveComponent("v-card-actions");
  const _component_v_dialog = _resolveComponent("v-dialog");

  return (__props.navKey)
    ? (_openBlock(), _createElementBlock("div", _hoisted_1, [
        _cache[42] || (_cache[42] = _createElementVNode("div", { class: "d-flex align-center pa-4" }, [
          _createElementVNode("div", { class: "text-h6" }, "115秒传")
        ], -1)),
        (error.value)
          ? (_openBlock(), _createBlock(_component_v_alert, {
              key: 0,
              type: "error",
              variant: "tonal",
              class: "mx-4 mb-3"
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(error.value), 1)
              ]),
              _: 1
            }))
          : _createCommentVNode("", true),
        (!enabled.value && !loading.value)
          ? (_openBlock(), _createBlock(_component_v_alert, {
              key: 1,
              type: "info",
              variant: "tonal",
              class: "mx-4 mb-3"
            }, {
              default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                _createTextVNode("插件已停用，仍可查看已有记录。", -1)
              ]))]),
              _: 1
            }))
          : _createCommentVNode("", true),
        _createVNode(_component_v_card, {
          variant: "outlined",
          class: "upload-summary mx-4 mb-4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_card_text, null, {
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_2, [
                  _createVNode(_component_v_icon, {
                    icon: "mdi-cloud-upload-outline",
                    size: "20"
                  }),
                  _cache[16] || (_cache[16] = _createTextVNode("上传任务", -1))
                ]),
                _createElementVNode("div", _hoisted_3, _toDisplayString(tasks.value.length), 1),
                _createElementVNode("div", _hoisted_4, "已上传 " + _toDisplayString(uploadedCount.value) + " / " + _toDisplayString(tasks.value.length) + " 个 · " + _toDisplayString(formatSize(uploadedBytes.value)) + " / " + _toDisplayString(formatSize(totalBytes.value)), 1),
                _createElementVNode("div", _hoisted_5, [
                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(summary.value, (item) => {
                    return (_openBlock(), _createBlock(_component_v_chip, {
                      key: item.state,
                      size: "small",
                      variant: "tonal",
                      color: stateColor(item.state)
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(item.label) + " " + _toDisplayString(item.count), 1)
                      ]),
                      _: 2
                    }, 1032, ["color"]))
                  }), 128))
                ]),
                (postStats.value && postStats.value.rpc_calls)
                  ? (_openBlock(), _createElementBlock("div", _hoisted_6, [
                      _createTextVNode("CD2 刷新 RPC " + _toDisplayString(postStats.value.rpc_calls) + " 次 · 合并目录 " + _toDisplayString(postStats.value.merged_directories || 0) + " 个", 1),
                      _cache[17] || (_cache[17] = _createElementVNode("br", null, null, -1)),
                      _cache[18] || (_cache[18] = _createTextVNode("RPC 次数不是115 API请求次数。", -1))
                    ]))
                  : _createCommentVNode("", true)
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_v_card, {
          variant: "outlined",
          class: "queue-card mx-4"
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_card_item, null, {
              default: _withCtx(() => [
                _createElementVNode("div", _hoisted_7, [
                  _createVNode(_component_v_text_field, {
                    modelValue: query.value,
                    "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((query).value = $event)),
                    placeholder: "搜索文件或路径",
                    "aria-label": "搜索文件或路径",
                    "prepend-inner-icon": "mdi-magnify",
                    density: "compact",
                    variant: "outlined",
                    flat: "",
                    "single-line": "",
                    "hide-details": "",
                    clearable: "",
                    class: "record-search"
                  }, null, 8, ["modelValue"]),
                  _createVNode(_component_v_select, {
                    modelValue: stateFilter.value,
                    "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((stateFilter).value = $event)),
                    items: stateOptions,
                    "aria-label": "筛选状态",
                    density: "compact",
                    variant: "outlined",
                    "hide-details": "",
                    class: "record-filter"
                  }, null, 8, ["modelValue"]),
                  _createVNode(_component_v_spacer),
                  _createVNode(_component_v_btn, {
                    icon: "mdi-refresh",
                    variant: "text",
                    loading: loading.value,
                    "aria-label": "刷新队列",
                    title: "刷新队列",
                    onClick: refresh
                  }, null, 8, ["loading"])
                ])
              ]),
              _: 1
            }),
            _createVNode(_component_v_data_table_virtual, {
              headers: headers,
              items: visibleTasks.value,
              "item-value": "id",
              loading: loading.value,
              "loading-text": "正在加载队列",
              density: "compact",
              "fixed-header": "",
              hover: "",
              height: "480",
              class: "records-table"
            }, {
              "item.file": _withCtx(({ item }) => [
                _createElementVNode("div", _hoisted_8, [
                  _createElementVNode("div", _hoisted_9, _toDisplayString(fileName(item.remote_path)), 1),
                  _createElementVNode("small", {
                    class: "record-path text-medium-emphasis",
                    title: item.remote_path
                  }, _toDisplayString(item.remote_path), 9, _hoisted_10)
                ])
              ]),
              "item.size": _withCtx(({ item }) => [
                _createElementVNode("span", _hoisted_11, _toDisplayString(formatSize(item.identity?.[2])), 1)
              ]),
              "item.ready": _withCtx(({ item }) => [
                _createElementVNode("small", null, _toDisplayString(_unref(formatTime)(item.ready_at)), 1)
              ]),
              "item.state": _withCtx(({ item }) => [
                _createVNode(_component_v_chip, {
                  size: "small",
                  color: stateColor(item.state),
                  variant: "tonal"
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(_unref(STATE_LABELS)[item.state] || item.state), 1)
                  ]),
                  _: 2
                }, 1032, ["color"]),
                (item.upload_mode === 'normal')
                  ? (_openBlock(), _createElementBlock("small", _hoisted_12, "普通上传"))
                  : _createCommentVNode("", true)
              ]),
              "item.postprocess": _withCtx(({ item }) => [
                (item.postprocess)
                  ? (_openBlock(), _createElementBlock("small", _hoisted_13, _toDisplayString(_unref(POSTPROCESS_LABELS)[item.postprocess.state] || item.postprocess.state), 1))
                  : (_openBlock(), _createElementBlock("span", _hoisted_14, "—"))
              ]),
              "item.progress": _withCtx(({ item }) => [
                (item.state === 'running')
                  ? (_openBlock(), _createElementBlock("div", _hoisted_15, [
                      _createElementVNode("div", _hoisted_16, _toDisplayString(stageLabel(item.progress?.stage)), 1),
                      _createVNode(_component_v_progress_linear, {
                        "model-value": percentage(item.progress),
                        indeterminate: item.progress?.stage !== 'uploading',
                        color: "primary",
                        rounded: "",
                        height: "6",
                        "aria-label": "任务处理进度"
                      }, null, 8, ["model-value", "indeterminate"]),
                      (item.progress?.stage === 'uploading')
                        ? (_openBlock(), _createElementBlock("div", _hoisted_17, _toDisplayString(percentage(item.progress).toFixed(1)) + "% · " + _toDisplayString(formatSize(item.progress?.bytes_per_second)) + "/s", 1))
                        : _createCommentVNode("", true)
                    ]))
                  : (_openBlock(), _createElementBlock("span", _hoisted_18, "—"))
              ]),
              "item.actions": _withCtx(({ item }) => [
                _createVNode(_component_v_btn, {
                  icon: "mdi-dots-vertical",
                  variant: "text",
                  size: "small",
                  "aria-label": "查看任务详情",
                  title: "查看任务详情",
                  onClick: $event => (openDetails(item))
                }, null, 8, ["onClick"])
              ]),
              "no-data": _withCtx(() => [
                _createTextVNode(_toDisplayString(tasks.value.length ? '没有匹配的任务' : '暂无上传任务'), 1)
              ]),
              _: 1
            }, 8, ["items", "loading"]),
            _createVNode(_component_v_divider),
            _createElementVNode("div", _hoisted_19, [
              _createVNode(_component_v_select, {
                modelValue: pageSize.value,
                "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((pageSize).value = $event)),
                items: [25, 50, 100],
                "aria-label": "每页条数",
                density: "compact",
                variant: "plain",
                "hide-details": "",
                class: "page-size"
              }, null, 8, ["modelValue"]),
              _createElementVNode("span", _hoisted_20, _toDisplayString(filteredTasks.value.length) + " 个任务", 1),
              _createVNode(_component_v_spacer),
              _createVNode(_component_v_pagination, {
                modelValue: page.value,
                "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((page).value = $event)),
                length: Math.max(1, pageCount.value),
                "total-visible": 5,
                "show-first-last-page": "",
                density: "compact"
              }, null, 8, ["modelValue", "length"])
            ])
          ]),
          _: 1
        }),
        (bdmv.value.tasks.length || bdmv.value.error)
          ? (_openBlock(), _createBlock(_component_v_card, {
              key: 2,
              variant: "outlined",
              class: "mx-4 mt-4"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_v_card_title, null, {
                  default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                    _createTextVNode("BDMV · CD2 上传", -1)
                  ]))]),
                  _: 1
                }),
                (bdmv.value.error)
                  ? (_openBlock(), _createBlock(_component_v_alert, {
                      key: 0,
                      type: "warning",
                      variant: "tonal",
                      class: "ma-3"
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(bdmv.value.error), 1)
                      ]),
                      _: 1
                    }))
                  : _createCommentVNode("", true),
                _createVNode(_component_v_data_table, {
                  headers: bdmvHeaders,
                  items: bdmv.value.tasks,
                  "items-per-page": 10,
                  density: "compact",
                  class: "records-table"
                }, {
                  "item.name": _withCtx(({ item }) => [
                    _createElementVNode("div", _hoisted_21, [
                      _createTextVNode(_toDisplayString(item.name), 1),
                      _createElementVNode("small", _hoisted_22, _toDisplayString(item.downloader) + " · " + _toDisplayString(item.target), 1)
                    ])
                  ]),
                  "item.state": _withCtx(({ item }) => [
                    _createVNode(_component_v_chip, {
                      size: "small",
                      color: item.state === 'done' ? 'success' : item.state === 'blocked' ? 'error' : 'primary'
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(bdmvLabels[item.state] || item.state), 1)
                      ]),
                      _: 2
                    }, 1032, ["color"]),
                    (item.error)
                      ? (_openBlock(), _createElementBlock("small", _hoisted_23, _toDisplayString(item.error), 1))
                      : _createCommentVNode("", true)
                  ]),
                  "item.progress": _withCtx(({ item }) => [
                    _createElementVNode("div", _hoisted_24, [
                      _createVNode(_component_v_progress_linear, {
                        "model-value": item.progress?.total_bytes ? Math.min(100, item.progress.uploaded_bytes / item.progress.total_bytes * 100) : 0,
                        indeterminate: ['submitting', 'unknown'].includes(item.state),
                        color: "primary",
                        height: "6",
                        rounded: ""
                      }, null, 8, ["model-value", "indeterminate"]),
                      _createElementVNode("small", null, _toDisplayString(item.progress?.uploaded || 0) + " / " + _toDisplayString(item.progress?.total || 0) + " 个文件 · " + _toDisplayString(formatSize(item.progress?.uploaded_bytes)), 1)
                    ])
                  ]),
                  _: 1
                }, 8, ["items"])
              ]),
              _: 1
            }))
          : _createCommentVNode("", true),
        _createVNode(_component_v_dialog, {
          modelValue: detailsOpen.value,
          "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((detailsOpen).value = $event)),
          "max-width": "720"
        }, {
          default: _withCtx(() => [
            (selectedTask.value)
              ? (_openBlock(), _createBlock(_component_v_card, { key: 0 }, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_card_title, { class: "d-flex align-center" }, {
                      default: _withCtx(() => [
                        _cache[20] || (_cache[20] = _createTextVNode("任务详情", -1)),
                        _createVNode(_component_v_spacer),
                        _createVNode(_component_v_btn, {
                          icon: "mdi-close",
                          variant: "text",
                          "aria-label": "关闭详情",
                          onClick: _cache[4] || (_cache[4] = $event => (detailsOpen.value = false))
                        })
                      ]),
                      _: 1
                    }),
                    _createVNode(_component_v_card_text, { class: "record-details" }, {
                      default: _withCtx(() => [
                        (actionError.value)
                          ? (_openBlock(), _createBlock(_component_v_alert, {
                              key: 0,
                              type: "error",
                              variant: "tonal",
                              class: "mb-3"
                            }, {
                              default: _withCtx(() => [
                                _createTextVNode(_toDisplayString(actionError.value), 1)
                              ]),
                              _: 1
                            }))
                          : _createCommentVNode("", true),
                        _createElementVNode("div", null, [
                          _cache[21] || (_cache[21] = _createElementVNode("strong", null, "文件：", -1)),
                          _createTextVNode(_toDisplayString(selectedTask.value.relative_path), 1)
                        ]),
                        _createElementVNode("div", null, [
                          _cache[22] || (_cache[22] = _createElementVNode("strong", null, "状态：", -1)),
                          _createTextVNode(_toDisplayString(_unref(STATE_LABELS)[selectedTask.value.state] || selectedTask.value.state), 1)
                        ]),
                        _createElementVNode("div", null, [
                          _cache[23] || (_cache[23] = _createElementVNode("strong", null, "115路径：", -1)),
                          _createTextVNode(_toDisplayString(selectedTask.value.remote_path), 1)
                        ]),
                        _createElementVNode("div", null, [
                          _cache[24] || (_cache[24] = _createElementVNode("strong", null, "登记时间：", -1)),
                          _createTextVNode(_toDisplayString(_unref(formatTime)(selectedTask.value.created_at)), 1)
                        ]),
                        _createElementVNode("div", null, [
                          _cache[25] || (_cache[25] = _createElementVNode("strong", null, "下次尝试：", -1)),
                          _createTextVNode(_toDisplayString(_unref(formatTime)(selectedTask.value.ready_at)), 1)
                        ]),
                        (selectedTask.value.upload_mode === 'normal')
                          ? (_openBlock(), _createElementBlock("div", _hoisted_25, [...(_cache[26] || (_cache[26] = [
                              _createElementVNode("strong", null, "方式：", -1),
                              _createTextVNode("普通上传", -1)
                            ]))]))
                          : _createCommentVNode("", true),
                        _createElementVNode("div", null, [
                          _cache[27] || (_cache[27] = _createElementVNode("strong", null, "尝试次数：", -1)),
                          _createTextVNode(_toDisplayString(selectedTask.value.attempts), 1)
                        ]),
                        (selectedTask.value.verification?.remote_bytes != null)
                          ? (_openBlock(), _createElementBlock("div", _hoisted_26, [
                              _cache[28] || (_cache[28] = _createElementVNode("strong", null, "大小校验：", -1)),
                              _createTextVNode("本地 " + _toDisplayString(selectedTask.value.verification.local_bytes) + " 字节 / 115 " + _toDisplayString(selectedTask.value.verification.remote_bytes) + " 字节", 1)
                            ]))
                          : _createCommentVNode("", true),
                        (selectedTask.value.error)
                          ? (_openBlock(), _createElementBlock("div", _hoisted_27, [
                              _cache[29] || (_cache[29] = _createElementVNode("strong", null, "说明：", -1)),
                              _createTextVNode(_toDisplayString(selectedTask.value.error), 1)
                            ]))
                          : _createCommentVNode("", true),
                        (selectedTask.value.postprocess)
                          ? (_openBlock(), _createElementBlock(_Fragment, { key: 4 }, [
                              _createVNode(_component_v_divider, { class: "my-3" }),
                              _createElementVNode("div", null, [
                                _cache[30] || (_cache[30] = _createElementVNode("strong", null, "上传后处理：", -1)),
                                _createTextVNode(_toDisplayString(selectedTask.value.postprocess.mode === 'strm' ? '本地生成 STRM' : selectedTask.value.postprocess.mode === 'cd2' ? '定向刷新 CD2' : '关闭') + " · " + _toDisplayString(_unref(POSTPROCESS_LABELS)[selectedTask.value.postprocess.state] || selectedTask.value.postprocess.state), 1)
                              ]),
                              (selectedTask.value.postprocess.target)
                                ? (_openBlock(), _createElementBlock("div", _hoisted_28, [
                                    _cache[31] || (_cache[31] = _createElementVNode("strong", null, "后处理目标：", -1)),
                                    _createTextVNode(_toDisplayString(selectedTask.value.postprocess.target), 1)
                                  ]))
                                : _createCommentVNode("", true),
                              _createElementVNode("div", null, [
                                _cache[32] || (_cache[32] = _createElementVNode("strong", null, "后处理尝试：", -1)),
                                _createTextVNode(_toDisplayString(selectedTask.value.postprocess.attempts || 0) + " 次 · 下次执行 " + _toDisplayString(_unref(formatTime)(selectedTask.value.postprocess.ready_at)), 1)
                              ]),
                              (selectedTask.value.postprocess.error)
                                ? (_openBlock(), _createElementBlock("div", _hoisted_29, _toDisplayString(selectedTask.value.postprocess.error), 1))
                                : _createCommentVNode("", true),
                              _cache[33] || (_cache[33] = _createElementVNode("p", { class: "text-caption text-medium-emphasis" }, "使用登记时固定的模式与映射；后处理失败不会重新上传。当前配置关闭时，待处理任务暂停。", -1))
                            ], 64))
                          : _createCommentVNode("", true),
                        (postAction.value === 'post_enqueue')
                          ? (_openBlock(), _createElementBlock("p", _hoisted_30, "此任务尚未执行后处理。手动补处理使用当前配置，只处理这一个任务，不重新上传。"))
                          : _createCommentVNode("", true)
                      ]),
                      _: 1
                    }),
                    (postAction.value)
                      ? (_openBlock(), _createBlock(_component_v_card_actions, { key: 0 }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_btn, {
                              disabled: acting.value || !enabled.value,
                              color: "primary",
                              onClick: _cache[5] || (_cache[5] = $event => (act(postAction.value)))
                            }, {
                              default: _withCtx(() => [...(_cache[34] || (_cache[34] = [
                                _createTextVNode("按当前配置补处理", -1)
                              ]))]),
                              _: 1
                            }, 8, ["disabled"])
                          ]),
                          _: 1
                        }))
                      : _createCommentVNode("", true),
                    (!['running', 'uploaded'].includes(selectedTask.value.state))
                      ? (_openBlock(), _createBlock(_component_v_card_actions, {
                          key: 1,
                          class: "flex-wrap ga-1"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_v_btn, {
                              disabled: acting.value,
                              onClick: _cache[6] || (_cache[6] = $event => (act('retry')))
                            }, {
                              default: _withCtx(() => [...(_cache[35] || (_cache[35] = [
                                _createTextVNode("重新校验 / 重试", -1)
                              ]))]),
                              _: 1
                            }, 8, ["disabled"]),
                            (hasConflict.value)
                              ? (_openBlock(), _createBlock(_component_v_btn, {
                                  key: 0,
                                  disabled: acting.value,
                                  onClick: _cache[7] || (_cache[7] = $event => (openResolution('rename')))
                                }, {
                                  default: _withCtx(() => [...(_cache[36] || (_cache[36] = [
                                    _createTextVNode("另存为", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["disabled"]))
                              : _createCommentVNode("", true),
                            (hasSizeConflict.value)
                              ? (_openBlock(), _createBlock(_component_v_btn, {
                                  key: 1,
                                  disabled: acting.value,
                                  color: "warning",
                                  onClick: _cache[8] || (_cache[8] = $event => (openResolution('overwrite')))
                                }, {
                                  default: _withCtx(() => [...(_cache[37] || (_cache[37] = [
                                    _createTextVNode("覆盖远端", -1)
                                  ]))]),
                                  _: 1
                                }, 8, ["disabled"]))
                              : _createCommentVNode("", true),
                            _createVNode(_component_v_btn, {
                              disabled: acting.value,
                              color: "error",
                              onClick: _cache[9] || (_cache[9] = $event => (act('cancel')))
                            }, {
                              default: _withCtx(() => [...(_cache[38] || (_cache[38] = [
                                _createTextVNode("取消任务", -1)
                              ]))]),
                              _: 1
                            }, 8, ["disabled"])
                          ]),
                          _: 1
                        }))
                      : _createCommentVNode("", true)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true)
          ]),
          _: 1
        }, 8, ["modelValue"]),
        _createVNode(_component_v_dialog, {
          modelValue: resolutionOpen.value,
          "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((resolutionOpen).value = $event)),
          "max-width": "560",
          persistent: acting.value
        }, {
          default: _withCtx(() => [
            _createVNode(_component_v_card, null, {
              default: _withCtx(() => [
                _createVNode(_component_v_card_title, null, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(resolution.value === 'rename' ? '另存为 · 保留双方' : '确认覆盖远端文件'), 1)
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_card_text, { class: "record-details" }, {
                  default: _withCtx(() => [
                    (actionError.value)
                      ? (_openBlock(), _createBlock(_component_v_alert, {
                          key: 0,
                          type: "error",
                          variant: "tonal",
                          class: "mb-3"
                        }, {
                          default: _withCtx(() => [
                            _createTextVNode(_toDisplayString(actionError.value), 1)
                          ]),
                          _: 1
                        }))
                      : _createCommentVNode("", true),
                    _createElementVNode("div", _hoisted_31, _toDisplayString(resolutionTask.value?.remote_path), 1),
                    (resolution.value === 'rename')
                      ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                          _createVNode(_component_v_text_field, {
                            modelValue: newFilename.value,
                            "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((newFilename).value = $event)),
                            label: "新的115文件名（含扩展名）",
                            variant: "outlined",
                            "hide-details": ""
                          }, null, 8, ["modelValue"]),
                          _cache[39] || (_cache[39] = _createElementVNode("div", { class: "text-caption mt-2" }, "仅修改此任务的115文件名，目录与本地文件不变。若新名称也已存在，会重新校验。", -1))
                        ], 64))
                      : (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
                          _createElementVNode("div", null, "本地 " + _toDisplayString(resolutionTask.value?.verification?.local_bytes) + " 字节 / 115 " + _toDisplayString(resolutionTask.value?.verification?.remote_bytes) + " 字节", 1),
                          _createVNode(_component_v_alert, {
                            type: "warning",
                            variant: "tonal",
                            class: "mt-3"
                          }, {
                            default: _withCtx(() => [...(_cache[40] || (_cache[40] = [
                              _createTextVNode("将先删除上述115文件，再上传本地文件。上传失败时原文件不会自动恢复；只有上传成功才会执行本地清理及后续标签处理。", -1)
                            ]))]),
                            _: 1
                          })
                        ], 64))
                  ]),
                  _: 1
                }),
                _createVNode(_component_v_card_actions, null, {
                  default: _withCtx(() => [
                    _createVNode(_component_v_spacer),
                    _createVNode(_component_v_btn, {
                      disabled: acting.value,
                      onClick: _cache[12] || (_cache[12] = $event => (resolutionOpen.value = false))
                    }, {
                      default: _withCtx(() => [...(_cache[41] || (_cache[41] = [
                        _createTextVNode("返回", -1)
                      ]))]),
                      _: 1
                    }, 8, ["disabled"]),
                    _createVNode(_component_v_btn, {
                      loading: acting.value,
                      color: resolution.value === 'overwrite' ? 'error' : 'primary',
                      onClick: _cache[13] || (_cache[13] = $event => (act(resolution.value)))
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(resolution.value === 'overwrite' ? '确认覆盖' : '另存并重试'), 1)
                      ]),
                      _: 1
                    }, 8, ["loading", "color"])
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
    : _createCommentVNode("", true)
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-28e83513"]]);

export { Page as default };
