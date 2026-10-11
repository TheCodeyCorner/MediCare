document.addEventListener("DOMContentLoaded", () => {

    /*
     * Password visibility toggles
     */
    const passwordToggles = document.querySelectorAll(".password-toggle");

    passwordToggles.forEach((toggle) => {

        toggle.addEventListener("click", () => {

            const targetId = toggle.getAttribute("data-password-target");
            const passwordInput = document.getElementById(targetId);
            const passwordIcon = toggle.querySelector("i");

            if (!passwordInput || !passwordIcon) {
                console.error("Password input not found:", targetId);
                return;
            }

            if (passwordInput.type === "password") {
                passwordInput.type = "text";

                passwordIcon.classList.remove("fa-eye");
                passwordIcon.classList.add("fa-eye-slash");

                toggle.setAttribute("aria-label", "Hide password");
                toggle.setAttribute("aria-pressed", "true");

            } else {
                passwordInput.type = "password";

                passwordIcon.classList.remove("fa-eye-slash");
                passwordIcon.classList.add("fa-eye");

                toggle.setAttribute("aria-label", "Show password");
                toggle.setAttribute("aria-pressed", "false");
            }
        });
    });


    /*
     * Registration form
     */
    const registerForm = document.getElementById("registerForm");

    if (!registerForm) {
        return;
    }

    registerForm.addEventListener("submit", async (event) => {
        event.preventDefault();

        const emailInput = document.getElementById("email");
        const passwordInput = document.getElementById("password");
        const confirmPasswordInput =
            document.getElementById("confirmPassword");

        const email = emailInput.value.trim();
        const password = passwordInput.value;
        const confirmPassword = confirmPasswordInput.value;

        /*
         * Client-side validation
         */
        if (!email || !password || !confirmPassword) {
            showDashboardToast("Please fill in all fields.","error");
            return;
        }

        if (password !== confirmPassword) {
            showDashboardToast("Passwords do not match.","error");
            return;
        }

        /*
         * Disable button while registration is processing
         */
        const submitButton =
            document.getElementById("registerSubmit");

        submitButton.disabled = true;
        submitButton.textContent = "Creating Account...";

        /*
         * Get Django CSRF token
         */
        const csrfToken = document.querySelector(
            "[name=csrfmiddlewaretoken]"
        )?.value;

        try {
            const response = await fetch("/api/register/", {
                method: "POST",

                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken
                },

                body: JSON.stringify({
                    email: email,
                    password: password
                })
            });

            const data = await response.json();

            if (!response.ok) {
                showDashboardToast("Registration failed.","error");

                submitButton.disabled = false;
                submitButton.textContent = "Create Account";

                return;
            }

            showDashboardToast(
                "Account created successfully.\nPlease check your inbox to verify your email address.",
                "success"
            );

            setTimeout(() => {
                window.location.href = "/login/";
            }, 3000);

        } catch (error) {
            console.error("Registration error:", error);

            showDashboardToast("Unable to connect to the server. Please try again.","error")

            submitButton.disabled = false;
            submitButton.textContent = "Create Account";
        }
    });
});

// Popup Dynamic

function showDashboardToast(message, type = "info") {
    const container = document.querySelector(".dashboard-toast-container");

    if (!container) {
        return;
    }

    const toast = document.createElement("div");

    toast.className = `dashboard-toast dashboard-toast--${type}`;

    toast.innerHTML = `
        <span class="dashboard-toast__message"></span>
        <button
            type="button"
            class="dashboard-toast__close"
            aria-label="Close"
        >
            &times;
        </button>
    `;

    toast.querySelector(".dashboard-toast__message").textContent = message;

    const closeButton = toast.querySelector(".dashboard-toast__close");

    const removeToast = () => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(-0.5rem)";

        setTimeout(() => {
            toast.remove();
        }, 200);
    };

    closeButton.addEventListener("click", removeToast);

    container.appendChild(toast);

    setTimeout(removeToast, 4000);
}