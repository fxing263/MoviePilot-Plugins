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
  get: async path => path.startsWith('plugin/config/') ? {} : { success: true, data: { tasks: [] } },
  post: async () => ({ success: true, message: '模拟操作' }),
}
</script>
