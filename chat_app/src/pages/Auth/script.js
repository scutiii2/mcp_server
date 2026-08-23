document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("form[data-auth-form]");
  if (!form) return;
  form.addEventListener("submit", () => {
    const submitButton = form.querySelector("button[type='submit']");
    if (submitButton) {
      submitButton.disabled = true;
    }
  });
});
