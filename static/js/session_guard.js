(function () {
  // After login/logout, browser Back must revalidate instead of restoring a stale page.
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) {
      window.location.reload();
    }
  });
})();
