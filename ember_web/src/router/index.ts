import { createRouter, createWebHistory } from "vue-router";
import ChatView from "../views/ChatView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "chat", component: ChatView },
    // Lazy: the tools page loads its own chunk only when first opened.
    { path: "/tools", name: "tools", component: () => import("../views/ToolsView.vue") },
  ],
});
