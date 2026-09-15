import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { P as PLUGIN_ID, S as STATE_LABELS } from './shared-DZMfIF0M.js';

const {createElementVNode:_createElementVNode,resolveComponent:_resolveComponent,createVNode:_createVNode,createTextVNode:_createTextVNode,withCtx:_withCtx,toDisplayString:_toDisplayString,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "pa-4" };
const _hoisted_2 = { class: "d-flex align-center mb-4" };
const _hoisted_3 = { class: "d-flex flex-wrap ga-3" };
const _hoisted_4 = { class: "d-flex mt-4" };

const {computed,onMounted,ref} = await importShared('vue');

const _sfc_main = {
  __name: 'Page',
  props: { api: { type: [Object, Function], default: () => ({}) }, pluginId: { type: String, default: PLUGIN_ID } },
  emits: ['switch', 'close'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const tasks = ref([]);
const loading = ref(false);
const enabled = ref(false);
const error = ref('');
const summary = computed(() => Object.entries(STATE_LABELS).map(([state, label]) => ({ state, label, count: tasks.value.filter(task => task.state === state).length })).filter(item => item.count));
const failedCount = computed(() => tasks.value.filter(task => task.error || ['failed', 'cleanup_failed'].includes(task.state)).length);
async function refresh() {
  if (loading.value) return
  loading.value = true;
  error.value = '';
  try {
    const response = await props.api.get(`plugin/${props.pluginId || PLUGIN_ID}/tasks`);
    if (response?.success !== true) throw new Error(response?.message || '读取状态失败')
    tasks.value = response.data?.tasks || [];
    enabled.value = response.data?.enabled === true;
    error.value = response.data?.error || '';
  } catch (failure) {
    error.value = failure?.message || String(failure);
  } finally {
    loading.value = false;
  }
}
onMounted(refresh);

return (_ctx, _cache) => {
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_chip = _resolveComponent("v-chip");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("div", _hoisted_2, [
      _cache[3] || (_cache[3] = _createElementVNode("div", { class: "text-h6" }, "115 延迟暂存", -1)),
      _createVNode(_component_v_spacer),
      _createVNode(_component_v_btn, {
        loading: loading.value,
        onClick: refresh
      }, {
        default: _withCtx(() => [...(_cache[2] || (_cache[2] = [
          _createTextVNode("刷新", -1)
        ]))]),
        _: 1
      }, 8, ["loading"])
    ]),
    (error.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 0,
          type: "error",
          variant: "tonal",
          class: "mb-4"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    _createVNode(_component_v_alert, {
      type: "info",
      variant: "tonal",
      class: "mb-4"
    }, {
      default: _withCtx(() => [
        _createTextVNode(_toDisplayString(enabled.value ? '自动处理已启用' : '插件已停用') + "。硬链接创建、删除和异常详情请查看插件日志。", 1)
      ]),
      _: 1
    }),
    _createElementVNode("div", _hoisted_3, [
      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(summary.value, (item) => {
        return (_openBlock(), _createBlock(_component_v_chip, {
          key: item.state
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(item.label) + "：" + _toDisplayString(item.count), 1)
          ]),
          _: 2
        }, 1024))
      }), 128))
    ]),
    (failedCount.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 1,
          type: "warning",
          variant: "tonal",
          class: "mt-4"
        }, {
          default: _withCtx(() => [
            _createTextVNode("有 " + _toDisplayString(failedCount.value) + " 项异常，请查看日志排查。", 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    _createElementVNode("div", _hoisted_4, [
      _createVNode(_component_v_btn, {
        variant: "text",
        onClick: _cache[0] || (_cache[0] = $event => (emit('switch')))
      }, {
        default: _withCtx(() => [...(_cache[4] || (_cache[4] = [
          _createTextVNode("配置", -1)
        ]))]),
        _: 1
      }),
      _createVNode(_component_v_spacer),
      _createVNode(_component_v_btn, {
        variant: "text",
        onClick: _cache[1] || (_cache[1] = $event => (emit('close')))
      }, {
        default: _withCtx(() => [...(_cache[5] || (_cache[5] = [
          _createTextVNode("关闭", -1)
        ]))]),
        _: 1
      })
    ])
  ]))
}
}

};

export { _sfc_main as default };
