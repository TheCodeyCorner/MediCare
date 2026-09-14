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
            alert("Please enter your email and password.");
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

                alert(
                    data.error || "Invalid email or password."
                );

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

            alert("Login failed.");

            submitButton.disabled = false;
            submitButton.textContent = "Sign In";


        } catch (error) {

            console.error("Login error:", error);

            alert(
                "Unable to connect to the server. Please try again."
            );

            submitButton.disabled = false;
            submitButton.textContent = "Sign In";

        }

    });

});
