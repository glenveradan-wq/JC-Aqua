(function () {
  function getModal(id) {
    return document.getElementById(id);
  }

  document.querySelectorAll("[data-open-modal]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      const modal = getModal(trigger.getAttribute("data-open-modal"));
      if (modal && typeof modal.showModal === "function") {
        modal.showModal();
      } else if (modal) {
        modal.setAttribute("open", "open");
      }
    });
  });

  document.querySelectorAll("[data-close-modal]").forEach((button) => {
    button.addEventListener("click", () => {
      const modal = button.closest("dialog");
      if (!modal) return;
      if (typeof modal.close === "function") {
        modal.close();
      } else {
        modal.removeAttribute("open");
      }
    });
  });

  document.querySelectorAll("dialog[data-app-modal][open]").forEach((modal) => {
    if (typeof modal.showModal === "function" && !modal.open) {
      modal.showModal();
    }
  });
})();
