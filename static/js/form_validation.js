(function () {
  "use strict";

  var MIN_LENGTH = 8;

  function findField(form, name) {
    return form.querySelector('[name="' + name + '"]');
  }

  function setCustomValidity(input, message) {
    if (!input) {
      return;
    }
    input.setCustomValidity(message || "");
  }

  function clearValidityOnInput(input) {
    if (!input) {
      return;
    }
    input.addEventListener("input", function () {
      input.setCustomValidity("");
    });
  }

  function scorePassword(password) {
    var score = 0;
    if (!password) {
      return 0;
    }
    if (password.length >= MIN_LENGTH) score += 1;
    if (/[a-z]/.test(password)) score += 1;
    if (/[A-Z]/.test(password)) score += 1;
    if (/[0-9]/.test(password)) score += 1;
    if (/[^A-Za-z0-9]/.test(password)) score += 1;
    return score;
  }

  function strengthMeta(score) {
    if (score <= 2) {
      return { level: "poor", label: "Poor", width: "33%" };
    }
    if (score <= 4) {
      return { level: "medium", label: "Medium", width: "66%" };
    }
    return { level: "hard", label: "Hard", width: "100%" };
  }

  function passwordPolicyMessage(password) {
    if (!password || password.length < MIN_LENGTH) {
      return "Password must be at least " + MIN_LENGTH + " characters.";
    }
    var missing = [];
    if (!/[A-Z]/.test(password)) missing.push("an uppercase letter");
    if (!/[a-z]/.test(password)) missing.push("a lowercase letter");
    if (!/[0-9]/.test(password)) missing.push("a number");
    if (missing.length) {
      return "Password must include " + missing.join(", ").replace(/, ([^,]*)$/, ", and $1") + ".";
    }
    return "";
  }

  function updateStrengthMeter(passwordInput) {
    var meter = passwordInput
      .closest(".form-field")
      .querySelector("[data-password-strength]");
    if (!meter) {
      return;
    }
    var fill = meter.querySelector("[data-password-strength-fill]");
    var label = meter.querySelector("[data-password-strength-label]");
    var checklist = meter.querySelectorAll("[data-password-rule]");
    var value = passwordInput.value || "";
    var score = scorePassword(value);
    var meta = strengthMeta(score);

    meter.hidden = !value;
    meter.setAttribute("data-level", meta.level);
    if (fill) {
      fill.style.width = value ? meta.width : "0%";
    }
    if (label) {
      label.textContent = value ? meta.label : "";
    }

    var rules = {
      length: value.length >= MIN_LENGTH,
      upper: /[A-Z]/.test(value),
      lower: /[a-z]/.test(value),
      number: /[0-9]/.test(value),
      special: /[^A-Za-z0-9]/.test(value),
    };
    checklist.forEach(function (item) {
      var key = item.getAttribute("data-password-rule");
      item.classList.toggle("is-met", !!rules[key]);
    });
  }

  function bindStrengthMeter(passwordInput) {
    if (!passwordInput || passwordInput.dataset.strengthBound === "1") {
      return;
    }
    passwordInput.dataset.strengthBound = "1";
    passwordInput.setAttribute("minlength", String(MIN_LENGTH));
    passwordInput.addEventListener("input", function () {
      updateStrengthMeter(passwordInput);
    });
    updateStrengthMeter(passwordInput);
  }

  function validatePasswordPair(form) {
    var password =
      findField(form, "password") || findField(form, "new_password");
    var confirm =
      findField(form, "confirm_password") ||
      findField(form, "confirm_new_password");
    if (!password || !confirm) {
      return true;
    }

    var passwordValue = password.value || "";
    var confirmValue = confirm.value || "";

    // Profile forms allow blank new password (no change).
    if (!passwordValue && !confirmValue && password.name === "new_password") {
      setCustomValidity(password, "");
      setCustomValidity(confirm, "");
      return true;
    }

    var policyMessage = passwordPolicyMessage(passwordValue);
    if (policyMessage) {
      setCustomValidity(password, policyMessage);
      password.reportValidity();
      return false;
    }

    if (passwordValue !== confirmValue) {
      setCustomValidity(confirm, "Passwords do not match.");
      confirm.reportValidity();
      return false;
    }

    setCustomValidity(password, "");
    setCustomValidity(confirm, "");
    return true;
  }

  function enhanceForm(form) {
    if (!form || form.dataset.validationBound === "1") {
      return;
    }
    form.dataset.validationBound = "1";

    var password =
      findField(form, "password") || findField(form, "new_password");
    var confirm =
      findField(form, "confirm_password") ||
      findField(form, "confirm_new_password");
    clearValidityOnInput(password);
    clearValidityOnInput(confirm);
    if (password) {
      bindStrengthMeter(password);
    }

    form.addEventListener("submit", function (event) {
      if (!form.checkValidity()) {
        event.preventDefault();
        form.reportValidity();
        return;
      }
      if (!validatePasswordPair(form)) {
        event.preventDefault();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document
      .querySelectorAll(
        "form[method='post'], form[method='POST'], form.profile-form, form.auth-form"
      )
      .forEach(enhanceForm);
  });
})();
