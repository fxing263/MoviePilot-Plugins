<script setup>
import TransferHistoryView from './src/views/reorganize/TransferHistoryView.vue'
import SharedDialogHost from './src/components/dialog/SharedDialogHost.vue'
</script>
<template><VApp class="rapid115-full-native"><RouterView /><TransferHistoryView /><SharedDialogHost /></VApp></template>
<style>
.rapid115-full-native.v-application { background: transparent; }
.rapid115-full-native > .v-application__wrap { min-height: 0; }
</style>
