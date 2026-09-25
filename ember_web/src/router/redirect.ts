/** Where to go after login. Only same-site paths: a crafted
 * ?redirect=https://evil.example (or //evil.example) must not send the user
 * off-site right after they typed their password. */
export function safeRedirect(value: unknown): string {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") ? value : "/";
}
