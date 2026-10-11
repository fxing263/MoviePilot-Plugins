<template>
  <v-app><v-main><v-container>
    <v-alert type="info" class="mb-4">本地预览：接口为模拟数据，不连接 MoviePilot 或 115。</v-alert>
    <Config v-if="showConfig" :api="api" @switch="showConfig = false" @save="saved = true" />
    <Page v-else :api="api" @switch="showConfig = true" />
    <v-alert v-if="saved" type="success">配置验证预览通过（未保存到服务器）</v-alert>
  </v-container></v-main></v-app>
</template>
<script setup>
import { ref } from 'vue'
import Config from './components/Config.vue'
import Page from './components/Page.vue'
const showConfig = ref(true)
const saved = ref(false)
const api = {
  get: async path => path === 'storage/directories'
    ? { success: true, data: [{ name: '电影', library_storage: 'local', library_path: '/media/电影' }] }
    : path === 'download/clients'
      ? [{ name: '主下载器', type: 'qbittorrent' }, { name: '备用下载器', type: 'qbittorrent' }]
      : { success: true, data: {} },
  post: async () => ({ success: true, message: '模拟操作' }),
}
</script>
