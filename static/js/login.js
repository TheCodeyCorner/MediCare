console.log("MediCare login.js loaded");

document.addEventListener("DOMContentLoaded", () => {

    // ============================================================
    // Password visibility toggle
    // ============================================================

    const passwordInput = document.getElementById("password");
    const passwordToggle = document.getElementById("passwordToggle");
    const passwordIcon = document.getElementById("passwordIcon");

    if (passwordInput && passwordToggle && passwordIcon) {

        passwordToggle.addEventListener("click", () => {

            const isVisible = passwordInput.type === "text";

            passwordInput.type = isVisible ? "password" : "text";

            passwordIcon.classList.toggle("fa-eye", isVisible);
            passwordIcon.classList.toggle("fa-eye-slash", !isVisible);

            passwordToggle.setAttribute(
                "aria-label",
                isVisible ? "Show password" : "Hide password"
            );

            passwordToggle.setAttribute(
                "aria-pressed",
                String(!isVisible)
            );

        });

    }


    // ============================================================
    // Login form
    // ============================================================

    const loginForm = document.getElementById("loginForm");

    if (!loginForm) {
        return;
    }


    loginForm.addEventListener("submit", async (event) => {

        event.preventDefault();


        // --------------------------------------------------------
        // Get form fields
        // --------------------------------------------------------

        const emailInput = document.getElementById("email");
        const passwordInput = document.getElementById("password");
        const submitButton = document.getElementById("loginSubmit");

        if (!emailInput || !passwordInput || !submitButton) {
            console.error("Login form elements are missing.");
            return;
        }


        const email = emailInput.value.trim();
        const password = passwordInput.value;


        // --------------------------------------------------------
        // Client-side validation
        // --------------------------------------------------------

        if (!email || !password) {
            showDashboardToast("Please enter your email and password","error");
            return;
        }


        // --------------------------------------------------------
        // Disable button while login is processing
        // --------------------------------------------------------

        submitButton.disabled = true;
        submitButton.textContent = "Signing In...";


        // --------------------------------------------------------
        // Get Django CSRF token
        // --------------------------------------------------------

        const csrfToken = document.querySelector(
            "[name=csrfmiddlewaretoken]"
        )?.value;


        try {

            // ----------------------------------------------------
            // Send login request to Django
            // ----------------------------------------------------

            const response = await fetch("/api/login/", {

                method: "POST",

                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken
                },

                credentials: "same-origin",

                body: JSON.stringify({
                    email: email,
                    password: password
                })

            });


            const data = await response.json();


            // ----------------------------------------------------
            // Login failed
            // ----------------------------------------------------

            if (!response.ok) {

                showDashboardToast("Invalid email or password.","error")

                submitButton.disabled = false;
                submitButton.textContent = "Sign In";

                return;
            }


            // ----------------------------------------------------
            // Login successful
            // ----------------------------------------------------

            if (data.success) {

                if (data.success) {

                    window.location.href =
                        data.redirect || "/patient/";

                    return;
                }

                window.location.href =
                    data.redirect || "/patient/";

                return;
            }


            // ----------------------------------------------------
            // Unexpected response
            // ----------------------------------------------------

            showDashboardToast("Login failed.","error")

            submitButton.disabled = false;
            submitButton.textContent = "Sign In";


        } catch (error) {

            console.error("Login error:", error);
            showDashboardToast("Unable to connect to the server. Please try again.","error")

            submitButton.disabled = false;
            submitButton.textContent = "Sign In";

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