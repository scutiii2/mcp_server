import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { configIssuesClient, type ConfigIssue } from "../api/ConfigIssuesClient";
import { errorMessage } from "../utils/errors";
import { useAuthStore } from "./auth";

/** Problems in ember_api's config and secret files. The nav rail shows its
 * alert, and the Config issues page opens, only while there are any. */
export const useConfigIssuesStore = defineStore("configIssues", () => {
  const auth = useAuthStore();

  const issues = ref<ConfigIssue[]>([]);
  const loading = ref(false);
  const error = ref("");
  let loaded: Promise<void> | null = null;

  const errorCount = computed(() => issues.value.filter((i) => i.severity === "error").length);
  const warningCount = computed(() => issues.value.length - errorCount.value);

  async function refresh(): Promise<void> {
    if (!auth.hasPermission("config.issues.view")) {
      issues.value = [];
      return;
    }
    loading.value = true;
    error.value = "";
    try {
      issues.value = await configIssuesClient.list();
    } catch (err) {
      error.value = errorMessage(err);
    } finally {
      loading.value = false;
    }
  }

  /** Loads once per login; the router guard awaits it. */
  function ensureLoaded(): Promise<void> {
    loaded ??= refresh();
    return loaded;
  }

  // Another account (or a freshly verified one) may see different issues.
  watch(
    () => `${auth.account?.id ?? ""}:${auth.account?.email_verified ?? ""}`,
    () => {
      issues.value = [];
      error.value = "";
      loaded = null;
      if (auth.account) void ensureLoaded();
    },
  );

  if (auth.account) void ensureLoaded();

  return { issues, loading, error, errorCount, warningCount, refresh, ensureLoaded };
});
