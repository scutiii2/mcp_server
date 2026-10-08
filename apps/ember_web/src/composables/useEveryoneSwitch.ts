import { computed, ref } from "vue";
import { commandsClient, type CapabilityInfo } from "../api/CommandsClient";
import { errorMessage } from "../utils/errors";

/** The admin's "turn a built-in capability on or off for everyone" flow: ask
 * first (the caller shows a ConfirmModal while `pending` is set), then switch it
 * in mcp_server and hand the updated capability to `onChanged`. */
export function useEveryoneSwitch(onChanged: (updated: CapabilityInfo) => void | Promise<void>) {
  const pending = ref<CapabilityInfo | null>(null);
  const switching = ref<string | null>(null);
  const error = ref("");

  const copy = computed(() => {
    const capability = pending.value;
    if (!capability) return { title: "", message: "", label: "" };
    const verb = capability.enabled ? "Turn off" : "Turn on";
    return {
      title: `${verb} capability`,
      message: `${verb} "${capability.label ?? capability.name}" for every mcp_server client (chat_app, agents, ember)?`,
      label: verb,
    };
  });

  function ask(capability: CapabilityInfo): void {
    pending.value = capability;
  }

  function cancel(): void {
    pending.value = null;
  }

  async function confirm(): Promise<void> {
    const capability = pending.value;
    pending.value = null;
    if (!capability) return;
    error.value = "";
    switching.value = capability.name;
    try {
      await onChanged(await commandsClient.setCapability(capability.name, !capability.enabled));
    } catch (err) {
      error.value = errorMessage(err);
    } finally {
      switching.value = null;
    }
  }

  return { pending, switching, error, copy, ask, cancel, confirm };
}
