<template>
  <div>
    <v-alert v-if="error" type="error" variant="tonal">{{ error }}</v-alert>
    <v-progress-linear v-else-if="loading" indeterminate color="primary" />
    <div ref="container" />
  </div>
</template>
<script setup>
import { getCurrentInstance, onMounted, onUnmounted, ref } from 'vue'
import { useTheme } from 'vuetify'
import { PLUGIN_ID } from './shared'
const props = defineProps({api:{type:[Object,Function],required:true},pluginId:{type:String,default:PLUGIN_ID}})
const container=ref(null), loading=ref(true), error=ref('')
const theme=useTheme()
const host=getCurrentInstance()?.appContext.config.globalProperties
let dispose, stylesheet, removed=false
onMounted(async()=>{
 try {
  const uri=props.api.getUri({url:`plugin/file/${props.pluginId}/native-dist/native.js`})
  const moduleUrl=new URL(uri,document.baseURI)
  moduleUrl.searchParams.set('v', __NATIVE_REVISION__)
  window.__rapid115NativeBase=props.api.getUri({url:''}).replace(/\/?$/, '/')
  stylesheet=document.createElement('link');stylesheet.rel='stylesheet';stylesheet.href=new URL(`style.css?v=${__NATIVE_REVISION__}`,moduleUrl).href
  const styled=new Promise((resolve,reject)=>{stylesheet.onload=resolve;stylesheet.onerror=()=>reject(new Error('原版整理页面样式加载失败'))})
  document.head.appendChild(stylesheet)
  const [native]=await Promise.all([import(/* @vite-ignore */ moduleUrl.href),styled])
  if(removed) return
  const state=host?.$pinia?.state?.value || {}
  dispose=await native.mount(container.value,{api:props.api,pluginId:props.pluginId,theme:theme.global.name.value,user:state.user?JSON.parse(JSON.stringify(state.user)):undefined,auth:state.auth?JSON.parse(JSON.stringify(state.auth)):undefined})
  if(removed) dispose()
 } catch(failure) { if(!removed) error.value=failure?.message || '原版整理页面加载失败' }
 finally { loading.value=false }
})
onUnmounted(()=>{removed=true;dispose?.();stylesheet?.remove()})
</script>
