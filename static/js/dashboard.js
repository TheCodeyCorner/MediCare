document.addEventListener("DOMContentLoaded", () => {

    /* ======================================================================
       Lucide Icons
       ====================================================================== */

    if (window.lucide) {
        lucide.createIcons();
    }


    /* ======================================================================
       Sidebar
       ====================================================================== */

    const sidebar = document.querySelector("[data-sidebar]");
    const overlay = document.querySelector("[data-nav-overlay]");
    const openButton = document.querySelector("[data-nav-open]");
    const closeButton = document.querySelector("[data-nav-close]");


    function openSidebar() {
        sidebar?.classList.add("is-open");
        overlay?.classList.add("is-open");
        openButton?.setAttribute("aria-expanded", "true");
    }


    function closeSidebar() {
        sidebar?.classList.remove("is-open");
        overlay?.classList.remove("is-open");
        openButton?.setAttribute("aria-expanded", "false");
    }


    openButton?.addEventListener("click", openSidebar);
    closeButton?.addEventListener("click", closeSidebar);
    overlay?.addEventListener("click", closeSidebar);


    /* ======================================================================
       Sidebar Submenus
       ====================================================================== */

    document
        .querySelectorAll("[data-submenu-toggle]")
        .forEach((button) => {

            button.addEventListener("click", () => {

                const id = button.dataset.submenuToggle;

                const group = document.querySelector(
                    `[data-nav-group="${id}"]`
                );

                if (!group) {
                    return;
                }

                group.classList.toggle("is-open");

            });

        });


    /* ======================================================================
       Automatically Open Active Submenu
       ====================================================================== */

    document
        .querySelectorAll(".md-nav__subitem.is-active")
        .forEach((activeItem) => {

            const group = activeItem.closest(".md-nav__group");

            group?.classList.add("is-open");

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