(function () {
  const form = document.querySelector("[data-otp-form]");
  if (!form) return;

  const hidden = document.getElementById("verification-code");
  const digits = Array.from(form.querySelectorAll("[data-otp-digit]"));
  const submitButton = form.querySelector("[data-otp-submit]");
  const submitLabel = form.querySelector("[data-otp-submit-label]");
  const submitLoading = form.querySelector("[data-otp-loading]");
  const timerValue = document.querySelector("[data-otp-timer-value]");
  const resendForm = document.querySelector("[data-otp-resend-form]");
  const resendButton = document.querySelector("[data-otp-resend]");
  const resendLabel = document.querySelector("[data-otp-resend-label]");
  const resendLoading = document.querySelector("[data-otp-resend-loading]");
  const resendCountdown = document.querySelector("[data-otp-resend-countdown]");

  let expiresSeconds = Number(form.getAttribute("data-expires-seconds") || "0");
  let resendSeconds = Number(form.getAttribute("data-resend-seconds") || "0");

  function formatClock(totalSeconds) {
    const safe = Math.max(0, Number(totalSeconds) || 0);
    const minutes = Math.floor(safe / 60);
    const seconds = safe % 60;
    return minutes + ":" + String(seconds).padStart(2, "0");
  }

  function syncHidden() {
    if (hidden) {
      hidden.value = digits.map((input) => input.value.replace(/\D/g, "")).join("");
    }
  }

  function focusDigit(index) {
    if (index >= 0 && index < digits.length) {
      digits[index].focus();
      digits[index].select();
    }
  }

  digits.forEach((input, index) => {
    input.addEventListener("input", () => {
      const value = input.value.replace(/\D/g, "").slice(-1);
      input.value = value;
      syncHidden();
      if (value && index < digits.length - 1) {
        focusDigit(index + 1);
      }
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Backspace" && !input.value && index > 0) {
        focusDigit(index - 1);
      }
      if (event.key === "ArrowLeft" && index > 0) {
        event.preventDefault();
        focusDigit(index - 1);
      }
      if (event.key === "ArrowRight" && index < digits.length - 1) {
        event.preventDefault();
        focusDigit(index + 1);
      }
    });

    input.addEventListener("paste", (event) => {
      event.preventDefault();
      const pasted = (event.clipboardData || window.clipboardData)
        .getData("text")
        .replace(/\D/g, "")
        .slice(0, digits.length);
      if (!pasted) return;
      digits.forEach((digitInput, digitIndex) => {
        digitInput.value = pasted[digitIndex] || "";
      });
      syncHidden();
      focusDigit(Math.min(pasted.length, digits.length - 1));
    });
  });

  form.addEventListener("submit", () => {
    syncHidden();
    if (submitButton) {
      submitButton.disabled = true;
    }
    if (submitLabel) submitLabel.hidden = true;
    if (submitLoading) submitLoading.hidden = false;
  });

  if (resendForm) {
    resendForm.addEventListener("submit", () => {
      if (resendButton) resendButton.disabled = true;
      if (resendLabel) resendLabel.hidden = true;
      if (resendLoading) resendLoading.hidden = false;
    });
  }

  function updateResendUi() {
    if (!resendButton || !resendLabel) return;
    const emailInput = form.querySelector('input[name="email"]');
    const hasEmail = !!(emailInput && emailInput.value);

    if (resendSeconds > 0) {
      resendButton.disabled = true;
      resendLabel.hidden = false;
      resendLabel.textContent = "Resend available in " + formatClock(resendSeconds);
      if (resendCountdown) {
        resendCountdown.hidden = false;
        resendCountdown.textContent =
          "You can request another code in " + formatClock(resendSeconds) + ".";
      }
      return;
    }

    if (!resendLoading || resendLoading.hidden) {
      resendButton.disabled = !hasEmail;
      resendLabel.hidden = false;
      resendLabel.textContent = "Resend code";
    }
    if (resendCountdown) {
      resendCountdown.hidden = true;
    }
  }

  function tick() {
    if (timerValue) {
      timerValue.textContent = formatClock(expiresSeconds);
      if (expiresSeconds > 0) expiresSeconds -= 1;
    }
    updateResendUi();
    if (resendSeconds > 0) resendSeconds -= 1;
  }

  tick();
  window.setInterval(tick, 1000);
  if (digits[0]) digits[0].focus();
})();
