document.querySelectorAll("[data-history-back]").forEach((backLink) => {
    backLink.addEventListener("click", (event) => {
        if (
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey ||
            !document.referrer
        ) {
            return;
        }

        const previousPage = new URL(document.referrer);
        if (previousPage.origin === window.location.origin && window.history.length > 1) {
            event.preventDefault();
            window.history.back();
        }
    });
});
