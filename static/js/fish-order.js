(() => {
  const form = document.querySelector(".fish-order-form");
  if (!form) return;

  const input = form.querySelector("#order-quantity");
  const totalEl = form.querySelector("[data-line-total]");
  const unitPrice = Number(form.dataset.unitPrice || "0");
  if (!input || !totalEl || !Number.isFinite(unitPrice)) return;

  const max = Number(input.max || "100");
  const min = Number(input.min || "1");

  function clamp(value) {
    if (!Number.isFinite(value)) return min;
    return Math.min(max, Math.max(min, value));
  }

  function renderTotal() {
    const qty = clamp(Number(input.value));
    input.value = String(qty);
    const total = unitPrice * qty;
    totalEl.textContent = `₱${total.toFixed(2)}`;
  }

  form.querySelectorAll("[data-qty-step]").forEach((button) => {
    button.addEventListener("click", () => {
      const step = Number(button.getAttribute("data-qty-step") || "0");
      input.value = String(clamp(Number(input.value) + step));
      renderTotal();
    });
  });

  input.addEventListener("input", renderTotal);
  renderTotal();
})();
