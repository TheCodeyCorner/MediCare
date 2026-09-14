document.addEventListener("DOMContentLoaded", () => {

    /*
     * Lucide icons
     */
    if (window.lucide) {
        lucide.createIcons();
    }


    /*
     * Sidebar
     */
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


    /*
     * Sidebar submenus
     */
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


    /*
     * Automatically open the group containing
     * the currently active submenu item.
     */
    document
        .querySelectorAll(".md-nav__subitem.is-active")
        .forEach((activeItem) => {

            const group = activeItem.closest(".md-nav__group");

            group?.classList.add("is-open");

        });

});