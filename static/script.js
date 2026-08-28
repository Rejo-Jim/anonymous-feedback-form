// ------------------------------------------------------------
// Toasts: auto-dismiss flash messages, allow manual close
// ------------------------------------------------------------
document.querySelectorAll(".toast").forEach((toast) => {
    const remove = () => {
        toast.style.transition = "opacity 0.15s ease";
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 150);
    };
    const closeBtn = toast.querySelector(".toast__close");
    if (closeBtn) closeBtn.addEventListener("click", remove);
    setTimeout(remove, 5000);
});

// ------------------------------------------------------------
// Button loading state on real form submits
// ------------------------------------------------------------
document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", (event) => {
        // Let native "required" validation block submission first.
        if (!form.checkValidity()) return;

        const submitBtn = form.querySelector("button[type='submit']");
        if (submitBtn && !submitBtn.classList.contains("is-loading")) {
            submitBtn.classList.add("is-loading");
            submitBtn.disabled = true;
        }
    });
});

// ------------------------------------------------------------
// Grievance form: live character count + inline description error
// ------------------------------------------------------------
const description = document.getElementById("description");
const charCount = document.getElementById("char-count");
const descriptionError = document.getElementById("description-error");
const grievanceForm = document.getElementById("grievance-form");

if (description && charCount) {
    const updateCount = () => {
        charCount.textContent = `${description.value.length} / 2000`;
    };
    description.addEventListener("input", updateCount);
    updateCount();
}

if (grievanceForm && description && descriptionError) {
    grievanceForm.addEventListener("submit", (event) => {
        if (description.value.trim().length === 0) {
            event.preventDefault();
            description.closest(".field").classList.add("has-error");
            descriptionError.hidden = false;
            description.focus();

            const submitBtn = grievanceForm.querySelector("button[type='submit']");
            if (submitBtn) {
                submitBtn.classList.remove("is-loading");
                submitBtn.disabled = false;
            }
        }
    });

    description.addEventListener("input", () => {
        if (description.value.trim().length > 0) {
            description.closest(".field").classList.remove("has-error");
            descriptionError.hidden = true;
        }
    });
}

// ------------------------------------------------------------
// Copy tracking ID to clipboard
// ------------------------------------------------------------
document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
        const value = button.getAttribute("data-copy");
        try {
            await navigator.clipboard.writeText(value);
        } catch (err) {
            // Clipboard API unavailable (e.g. non-HTTPS local access);
            // fall back to a manual selection prompt.
            window.prompt("Copy this tracking ID:", value);
        }
        const labelEl = button.querySelector(".ticket__copy-label");
        const originalLabel = labelEl ? labelEl.textContent : button.textContent;
        if (labelEl) labelEl.textContent = "Copied";
        button.classList.add("is-copied");
        setTimeout(() => {
            if (labelEl) labelEl.textContent = originalLabel;
            button.classList.remove("is-copied");
        }, 1800);
    });
});
