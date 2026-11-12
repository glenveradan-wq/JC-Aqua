(function () {
  "use strict";

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

    if (passwordValue && passwordValue.length < 10) {
      setCustomValidity(
        password,
        "Password must be at least 10 characters long."
      );
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
