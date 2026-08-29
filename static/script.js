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

        // Use the button that was actually clicked (event.submitter), not
        // just the first submit button in the form - some forms (like the
        // satisfaction Yes/No form) have more than one, and disabling the
        // wrong one - or disabling the right one too early - drops its
        // name/value pair from the submitted form data entirely.
        const submitBtn = event.submitter || form.querySelector("button[type='submit']");
        if (submitBtn && submitBtn.tagName === "BUTTON" && !submitBtn.classList.contains("is-loading")) {
            submitBtn.classList.add("is-loading");
            // Defer the actual disabling to the next tick: disabling a
            // submit button synchronously inside its own "submit" handler
            // excludes it from the form data the browser is about to send
            // (per the HTML spec), which silently strips out which button
            // was pressed.
            setTimeout(() => { submitBtn.disabled = true; }, 0);
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
// Attachment field: show the chosen filename, support drag-and-drop
// onto the drop zone, and give quick feedback on obviously-wrong files.
// Actual validation (type/size/metadata stripping) happens server-side.
// ------------------------------------------------------------
const attachmentInput = document.getElementById("attachment");
const fileDrop = document.getElementById("file-drop");
const fileDropText = document.getElementById("file-drop-text");
const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024;

if (attachmentInput && fileDrop && fileDropText) {
    const defaultText = fileDropText.textContent;

    const showSelectedFile = () => {
        const file = attachmentInput.files && attachmentInput.files[0];
        if (!file) {
            fileDropText.textContent = defaultText;
            fileDrop.classList.remove("has-file");
            return;
        }
        if (file.size > MAX_ATTACHMENT_BYTES) {
            fileDropText.textContent = "That file is over 25 MB — please choose a smaller one.";
            fileDrop.classList.remove("has-file");
            attachmentInput.value = "";
            return;
        }
        fileDropText.textContent = `${file.name} selected`;
        fileDrop.classList.add("has-file");
    };

    attachmentInput.addEventListener("change", showSelectedFile);

    ["dragenter", "dragover"].forEach((evt) => {
        fileDrop.addEventListener(evt, (e) => {
            e.preventDefault();
            fileDrop.classList.add("is-dragover");
        });
    });

    ["dragleave", "drop"].forEach((evt) => {
        fileDrop.addEventListener(evt, (e) => {
            e.preventDefault();
            fileDrop.classList.remove("is-dragover");
        });
    });

    fileDrop.addEventListener("drop", (e) => {
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
            attachmentInput.files = e.dataTransfer.files;
            showSelectedFile();
        }
    });
}

// ------------------------------------------------------------
// Feedback form: star rating widget + require rating or message
// ------------------------------------------------------------
const starRating = document.getElementById("star-rating");

if (starRating) {
    const hiddenInput = document.getElementById("rating-value");
    const stars = Array.from(starRating.querySelectorAll(".star-btn"));

    const paint = (value) => {
        stars.forEach((star) => {
            const starValue = Number(star.dataset.value);
            star.classList.toggle("is-filled", starValue <= value);
            star.setAttribute("aria-checked", starValue === value ? "true" : "false");
        });
    };

    stars.forEach((star) => {
        star.addEventListener("click", () => {
            const value = Number(star.dataset.value);
            // Clicking the currently-selected star clears the rating.
            if (hiddenInput.value === String(value)) {
                hiddenInput.value = "";
                paint(0);
            } else {
                hiddenInput.value = String(value);
                paint(value);
            }
        });
        star.addEventListener("mouseenter", () => paint(Number(star.dataset.value)));
        star.addEventListener("focus", () => paint(Number(star.dataset.value)));
    });

    starRating.addEventListener("mouseleave", () => paint(Number(hiddenInput.value) || 0));
}

const feedbackForm = document.getElementById("feedback-form");
const feedbackMessage = document.getElementById("message");
const feedbackRatingInput = document.getElementById("rating-value");

if (feedbackForm && feedbackMessage && feedbackRatingInput) {
    feedbackForm.addEventListener("submit", (event) => {
        const hasMessage = feedbackMessage.value.trim().length > 0;
        const hasRating = feedbackRatingInput.value.trim().length > 0;
        if (!hasMessage && !hasRating) {
            event.preventDefault();
            feedbackMessage.focus();

            const submitBtn = feedbackForm.querySelector("button[type='submit']");
            if (submitBtn) {
                submitBtn.classList.remove("is-loading");
                submitBtn.disabled = false;
            }
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