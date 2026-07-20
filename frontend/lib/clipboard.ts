/**
 * copyText — clipboard copy that NEVER throws.
 *
 * navigator.clipboard.writeText rejects when the document isn't focused,
 * permissions are denied (iframes, some Android WebViews) or the context
 * isn't "secure". Uncaught, that surfaces as a console PAGEERROR and can
 * break the caller's flow. Falls back to the legacy execCommand path and
 * reports success so callers can show "copied ✓" vs a graceful hint.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to legacy path
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}
