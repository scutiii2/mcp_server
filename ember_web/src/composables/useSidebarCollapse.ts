import { ref, type Ref } from "vue";

const STORAGE_KEY = "ember_web.chatSidebarCollapsed";

// Per-browser convenience: blocked storage just means "expanded".
function readStored(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeStored(collapsed: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
  } catch {
    // ignore - see readStored
  }
}

/** Whether the chat page's conversation list is folded away, remembered per browser. */
export function useSidebarCollapse(): { collapsed: Ref<boolean>; toggle: () => void } {
  const collapsed = ref(readStored());
  function toggle(): void {
    collapsed.value = !collapsed.value;
    writeStored(collapsed.value);
  }
  return { collapsed, toggle };
}
