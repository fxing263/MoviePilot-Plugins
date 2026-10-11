import { createRouter, createMemoryHistory } from 'vue-router'
export default createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{render:()=>null}}]})
