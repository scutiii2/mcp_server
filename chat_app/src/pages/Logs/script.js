document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("select[data-autosubmit]").forEach((select) => {
    select.addEventListener("change", () => select.form.submit());
  });
});
