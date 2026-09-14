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
            alert("Please fill in all fields.");
            return;
        }

        if (password !== confirmPassword) {
            alert("Passwords do not match.");
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
                alert(data.error || "Registration failed.");

                submitButton.disabled = false;
                submitButton.textContent = "Create Account";

                return;
            }

            alert(data.message || "Account created successfully.");

            window.location.href = "/login/";

        } catch (error) {
            console.error("Registration error:", error);

            alert(
                "Unable to connect to the server. Please try again."
            );

            submitButton.disabled = false;
            submitButton.textContent = "Create Account";
        }
    });
});