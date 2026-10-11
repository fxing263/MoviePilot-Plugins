import { d as v, c as x, r as a, a as $, b as k, u as f, o as D, w as s, e as n, f as b, i as p, g as r, t as d } from "./entry-ClFWx1Su.js";
const H = { class: "d-flex flex-column flex-lg-row justify-center my-3" }, N = /* @__PURE__ */ v({
  __name: "TransferHistoryDeleteDialog",
  props: {
    modelValue: { type: Boolean, default: !0 },
    title: { default: "" }
  },
  emits: ["close", "delete", "update:modelValue"],
  setup(V, { emit: y }) {
    const c = V, i = y, l = x({
      get: () => c.modelValue,
      set: (t) => {
        i("update:modelValue", t), t || i("close");
      }
    });
    function u(t, e) {
      i("delete", t, e);
    }
    return (t, e) => {
      const C = a("VDialogCloseBtn"), B = a("VCardTitle"), m = a("VBtn"), _ = a("VCard"), g = a("VBottomSheet");
      return f(l) ? (D(), $(g, {
        key: 0,
        modelValue: f(l),
        "onUpdate:modelValue": e[5] || (e[5] = (o) => p(l) ? l.value = o : null),
        inset: ""
      }, {
        default: s(() => [
          n(_, { class: "text-center" }, {
            default: s(() => [
              n(C, {
                modelValue: f(l),
                "onUpdate:modelValue": e[0] || (e[0] = (o) => p(l) ? l.value = o : null)
              }, null, 8, ["modelValue"]),
              n(B, { class: "pe-10" }, {
                default: s(() => [
                  r(d(c.title), 1)
                ]),
                _: 1
              }),
              b("div", H, [
                n(m, {
                  color: "primary",
                  class: "mb-2 mx-2",
                  onClick: e[1] || (e[1] = (o) => u(!1, !1))
                }, {
                  default: s(() => [
                    r(d(t.$t("transferHistory.deleteRecordOnly")), 1)
                  ]),
                  _: 1
                }),
                n(m, {
                  color: "warning",
                  class: "mb-2 mx-2",
                  onClick: e[2] || (e[2] = (o) => u(!0, !1))
                }, {
                  default: s(() => [
                    r(d(t.$t("transferHistory.deleteSourceOnly")), 1)
                  ]),
                  _: 1
                }),
                n(m, {
                  color: "info",
                  class: "mb-2 mx-2",
                  onClick: e[3] || (e[3] = (o) => u(!1, !0))
                }, {
                  default: s(() => [
                    r(d(t.$t("transferHistory.deleteDestOnly")), 1)
                  ]),
                  _: 1
                }),
                n(m, {
                  color: "error",
                  class: "mb-2 mx-2",
                  onClick: e[4] || (e[4] = (o) => u(!0, !0))
                }, {
                  default: s(() => [
                    r(d(t.$t("transferHistory.deleteAll")), 1)
                  ]),
                  _: 1
                })
              ])
            ]),
            _: 1
          })
        ]),
        _: 1
      }, 8, ["modelValue"])) : k("", !0);
    };
  }
});
export {
  N as default
};
