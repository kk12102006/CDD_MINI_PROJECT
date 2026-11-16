document.addEventListener("DOMContentLoaded", () => {
    const password = document.querySelector("#password");
    const confirmation = document.querySelector("#confirm_password");

    if (password && confirmation) {
        confirmation.addEventListener("input", () => {
            confirmation.setCustomValidity(
                confirmation.value && confirmation.value !== password.value
                    ? "The passwords do not match."
                    : ""
            );
        });
        password.addEventListener("input", () => {
            confirmation.setCustomValidity(
                confirmation.value && confirmation.value !== password.value
                    ? "The passwords do not match."
                    : ""
            );
        });
    }

    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm(form.dataset.confirm)) {
                event.preventDefault();
            }
        });
    });
});