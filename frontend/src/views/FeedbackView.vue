<script setup>
import FeedbackForm from '../components/FeedbackForm.vue'
</script>

<template>
  <div class="view">
    <div class="view-inner feedback-view">
      <header class="view-head"><h1 class="serif">意见反馈</h1></header>
      <section class="card"><FeedbackForm /></section>
    </div>
  </div>
</template>

<style scoped>
.feedback-view { max-width: 680px }
.card { padding: clamp(16px, 4vw, 32px) }
</style>
