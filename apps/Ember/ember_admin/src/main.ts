import { createApp } from "vue";
import { createPinia } from "pinia";
import "./style.css";
import { initTheme } from "./composables/useTheme";
import App from "./App.vue";
import { router } from "./router";

initTheme();

createApp(App).use(createPinia()).use(router).mount("#app");
