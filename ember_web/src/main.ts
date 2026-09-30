import { createApp } from "vue";
import { createPinia } from "pinia";
import "./style.css";
import App from "./App.vue";
import { initTheme } from "./composables/useTheme";
import { router } from "./router";

initTheme();
createApp(App).use(createPinia()).use(router).mount("#app");
