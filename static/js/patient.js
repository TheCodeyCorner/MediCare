console.log("PATIENT.JS LOADED");
/**
 * Medicare — Patient Details
 * Vanilla JS behaviour, converted from the React `useState` menu toggle
 * and the appointments tab list. No build step / framework required.
 */
(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        initIcons();
        initMobileNav();
        initAppointmentTabs();
        initSelectAllCheckboxes();
    });

    /* ---------------------------------------------------------------------
     * Icons — renders every <i data-lucide="..."> tag as an inline SVG.
     * Requires the lucide UMD build to be loaded on the page (see the
     * <script src="https://unpkg.com/lucide@latest/...">  tag in the HTML).
     * ------------------------------------------------------------------- */
    function initIcons() {
        if (window.lucide && typeof window.lucide.createIcons === "function") {
            window.lucide.createIcons();
        } else {
            // lucide loads with `defer`, so it may not be ready yet — retry once.
            window.addEventListener("load", function () {
                if (window.lucide) window.lucide.createIcons();
            });
        }
    }

    /* ---------------------------------------------------------------------
     * Mobile nav drawer — mirrors: const [menuOpen, setMenuOpen] = useState(false)
     * ------------------------------------------------------------------- */
    function initMobileNav() {
        var openBtn = document.querySelector("[data-nav-open]");
        var closeBtn = document.querySelector("[data-nav-close]");
        var overlay = document.querySelector("[data-nav-overlay]");
        var sidebar = document.querySelector("[data-sidebar]");

        if (!sidebar) return;

        function setOpen(isOpen) {
            sidebar.classList.toggle("is-open", isOpen);
            if (overlay) overlay.classList.toggle("is-open", isOpen);
            if (openBtn) openBtn.setAttribute("aria-expanded", String(isOpen));
        }

        if (openBtn) openBtn.addEventListener("click", function () { setOpen(true); });
        if (closeBtn) closeBtn.addEventListener("click", function () { setOpen(false); });
        if (overlay) overlay.addEventListener("click", function () { setOpen(false); });

        // Close the drawer automatically if the viewport grows past the
        // desktop breakpoint (matches the lg:translate-x-0 behaviour).
        var desktopQuery = window.matchMedia("(min-width: 1024px)");
        function handleBreakpointChange(e) {
            if (e.matches) setOpen(false);
        }
        if (desktopQuery.addEventListener) {
            desktopQuery.addEventListener("change", handleBreakpointChange);
        } else if (desktopQuery.addListener) {
            desktopQuery.addListener(handleBreakpointChange); // Safari <14 fallback
        }

        // Escape key closes the drawer.
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape") setOpen(false);
        });
    }

    /* ---------------------------------------------------------------------
     * Appointments — All / Upcoming / History tabs
     * ------------------------------------------------------------------- */
    function initAppointmentTabs() {
        var tabLists = document.querySelectorAll("[data-tabs]");

        tabLists.forEach(function (tabList) {
            var tabs = tabList.querySelectorAll("[data-tab]");
            var panelSelector = tabList.getAttribute("data-tabs");
            var rows = panelSelector ? document.querySelectorAll(panelSelector + " [data-tab-value]") : [];

            tabs.forEach(function (tab) {
                tab.addEventListener("click", function () {
                    tabs.forEach(function (t) {
                        t.classList.remove("tab-active");
                        t.classList.add("tab");
                    });
                    tab.classList.remove("tab");
                    tab.classList.add("tab-active");

                    var value = tab.getAttribute("data-tab");
                    rows.forEach(function (row) {
                        var matches = value === "all" || row.getAttribute("data-tab-value") === value;
                        row.style.display = matches ? "" : "none";
                    });
                });
            });
        });
    }

    /* ---------------------------------------------------------------------
     * "Select all" header checkbox for the prescriptions / appointments tables
     * ------------------------------------------------------------------- */
    function initSelectAllCheckboxes() {
        var selectAlls = document.querySelectorAll("[data-select-all]");

        selectAlls.forEach(function (selectAll) {
            var tableBody = selectAll.closest("table");
            if (!tableBody) return;
            var rowCheckboxes = tableBody.querySelectorAll("tbody [data-row-check]");

            selectAll.addEventListener("change", function () {
                rowCheckboxes.forEach(function (cb) { cb.checked = selectAll.checked; });
            });

            rowCheckboxes.forEach(function (cb) {
                cb.addEventListener("change", function () {
                    selectAll.checked = Array.prototype.every.call(rowCheckboxes, function (c) { return c.checked; });
                });
            });
        });
    }
})();


/* ---------------------------------------------------------------------
 * Blood Pressure chart
 * ------------------------------------------------------------------- */

document.addEventListener("DOMContentLoaded", () => {
    if (window.lucide) {
        lucide.createIcons();
    }

    initBloodPressureChart();
});


function initBloodPressureChart() {
    const chart = document.querySelector("[data-blood-pressure-chart]");
    const dataElement = document.getElementById("blood-pressure-data");

    if (!chart || !dataElement) {
        return;
    }

    let readings;

    try {
        readings = JSON.parse(dataElement.textContent);
    } catch (error) {
        console.error("Unable to parse blood pressure data.", error);
        return;
    }

    if (!Array.isArray(readings) || readings.length === 0) {
        return;
    }

    const systolicLine = chart.querySelector(
        '[data-chart-line="systolic"]'
    );

    const diastolicLine = chart.querySelector(
        '[data-chart-line="diastolic"]'
    );

    const heartRateLine = chart.querySelector(
        '[data-chart-line="heart-rate"]'
    );

    const pointsContainer = chart.querySelector(
        "[data-chart-points]"
    );

    if (!systolicLine || !diastolicLine || !heartRateLine) {
        console.error("Blood pressure chart lines were not found.");
        return;
    }

    const width = 1200;
    const height = 280;

    /*
     * Shared scale:
     *
     * 180 = high systolic range
     * 120 = normal-ish BP middle
     * 60  = normal-ish lower BP / heart rate range
     * 40  = low heart rate boundary
     */
    const minValue = 40;
    const maxValue = 180;


    function getX(index) {
        if (readings.length === 1) {
            return width / 2;
        }

        return (
            index / (readings.length - 1)
        ) * width;
    }


    function getY(value) {
        const numericValue = Number(value);

        if (!Number.isFinite(numericValue)) {
            return height;
        }

        const clamped = Math.min(
            maxValue,
            Math.max(minValue, numericValue)
        );

        return (
            height -
            (
                (clamped - minValue) /
                (maxValue - minValue)
            ) * height
        );
    }


    /*
     * Build each line independently.
     */

    const systolicPoints = readings
        .map((reading, index) => {
            return `${getX(index)},${getY(reading.systolic)}`;
        })
        .join(" ");


    const diastolicPoints = readings
        .map((reading, index) => {
            return `${getX(index)},${getY(reading.diastolic)}`;
        })
        .join(" ");


    const heartRatePoints = readings
        .map((reading, index) => {
            return `${getX(index)},${getY(reading.heart_rate)}`;
        })
        .join(" ");


    /*
     * Render SVG lines.
     */

    systolicLine.setAttribute(
        "points",
        systolicPoints
    );

    diastolicLine.setAttribute(
        "points",
        diastolicPoints
    );

    heartRateLine.setAttribute(
        "points",
        heartRatePoints
    );


    /*
     * Add interactive points for blood pressure.
     */

    if (pointsContainer) {
        pointsContainer.innerHTML = "";

        readings.forEach((reading, index) => {
            const systolic = Number(reading.systolic);
            const diastolic = Number(reading.diastolic);
            const heartRate = Number(reading.heart_rate);

            if (
                !Number.isFinite(systolic) ||
                !Number.isFinite(diastolic)
            ) {
                return;
            }

            const point = document.createElement("button");

            point.type = "button";
            point.className = "md-chart__point";

            if (index < 3) {
                point.classList.add("tooltip-right");
            }

            if (index >= readings.length - 3) {
                point.classList.add("tooltip-left");
            }

            const xPercent =
                readings.length === 1
                    ? 50
                    : (index / (readings.length - 1)) * 100;

            const averageBloodPressure =
                (systolic + diastolic) / 2;

            const yPercent =
                (getY(averageBloodPressure) / height) * 100;

            point.style.left = `${xPercent}%`;
            point.style.top = `${yPercent}%`;

            point.setAttribute(
                "aria-label",
                `${reading.month}: Blood pressure ${systolic}/${diastolic} mmHg, heart rate ${heartRate} bpm`
            );

            point.dataset.tooltip =
                `${reading.month}  •  ${systolic}/${diastolic} mmHg  •  ${heartRate} bpm`;

            pointsContainer.appendChild(point);
        });
    }
}

document.addEventListener("DOMContentLoaded", function () {

    const popup = document.getElementById(
        "profileCompletionPopup"
    );

    const closeButton = document.getElementById(
        "profileCompletionClose"
    );

    const laterButton = document.getElementById(
        "profileCompletionLater"
    );

    console.log("Popup:", popup);
    console.log("Close button:", closeButton);
    console.log("Later button:", laterButton);

    if (closeButton) {
        closeButton.addEventListener("click", function () {

            fetch("/api/patient/profile-popup/dismiss/", {
                method: "POST",
                headers: {
                    "X-CSRFToken": getCookie("csrftoken"),
                    "Content-Type": "application/json"
                }
            })
                .then(function (response) {
                    if (response.ok) {
                        popup.style.display = "none";
                    }
                });

        });
    }

    if (laterButton) {
        laterButton.addEventListener("click", function () {

            fetch("/api/patient/profile-popup/dismiss/", {
                method: "POST",
                headers: {
                    "X-CSRFToken": getCookie("csrftoken"),
                    "Content-Type": "application/json"
                }
            })
                .then(function (response) {
                    if (response.ok) {
                        popup.style.display = "none";
                    }
                });

        });
    }

});

function getCookie(name) {
    const cookies = document.cookie.split(";");

    for (let cookie of cookies) {
        cookie = cookie.trim();

        if (cookie.startsWith(name + "=")) {
            return decodeURIComponent(
                cookie.substring(name.length + 1)
            );
        }
    }

    return null;
}