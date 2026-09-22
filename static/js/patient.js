console.log("PATIENT.JS LOADED");

/**
 * Medicare — Patient Details
 * Vanilla JavaScript behaviour.
 */


/* ==========================================================================
 * Core Patient Page Initialization
 * ========================================================================== */

(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        initIcons();
        initMobileNav();
        initAppointmentTabs();
        initSelectAllCheckboxes();
    });


    /* ==========================================================================
     * Icons
     * ========================================================================== */

    function initIcons() {

        if (
            window.lucide &&
            typeof window.lucide.createIcons === "function"
        ) {
            window.lucide.createIcons();
            return;
        }

        window.addEventListener("load", function () {

            if (
                window.lucide &&
                typeof window.lucide.createIcons === "function"
            ) {
                window.lucide.createIcons();
            }

        });

    }


    /* ==========================================================================
     * Mobile Navigation
     * ========================================================================== */

    function initMobileNav() {

        var openBtn = document.querySelector("[data-nav-open]");
        var closeBtn = document.querySelector("[data-nav-close]");
        var overlay = document.querySelector("[data-nav-overlay]");
        var sidebar = document.querySelector("[data-sidebar]");

        if (!sidebar) {
            return;
        }


        function setOpen(isOpen) {

            sidebar.classList.toggle(
                "is-open",
                isOpen
            );

            if (overlay) {
                overlay.classList.toggle(
                    "is-open",
                    isOpen
                );
            }

            if (openBtn) {
                openBtn.setAttribute(
                    "aria-expanded",
                    String(isOpen)
                );
            }

        }


        if (openBtn) {
            openBtn.addEventListener(
                "click",
                function () {
                    setOpen(true);
                }
            );
        }


        if (closeBtn) {
            closeBtn.addEventListener(
                "click",
                function () {
                    setOpen(false);
                }
            );
        }


        if (overlay) {
            overlay.addEventListener(
                "click",
                function () {
                    setOpen(false);
                }
            );
        }


        var desktopQuery = window.matchMedia(
            "(min-width: 1024px)"
        );


        function handleBreakpointChange(event) {

            if (event.matches) {
                setOpen(false);
            }

        }


        if (desktopQuery.addEventListener) {

            desktopQuery.addEventListener(
                "change",
                handleBreakpointChange
            );

        } else if (desktopQuery.addListener) {

            desktopQuery.addListener(
                handleBreakpointChange
            );

        }


        document.addEventListener(
            "keydown",
            function (event) {

                if (event.key === "Escape") {
                    setOpen(false);
                }

            }
        );

    }


    /* ==========================================================================
     * Appointment Tabs
     * ========================================================================== */

    function initAppointmentTabs() {

        var tabLists = document.querySelectorAll(
            "[data-tabs]"
        );


        tabLists.forEach(function (tabList) {

            var tabs = tabList.querySelectorAll(
                "[data-tab]"
            );

            var panelSelector =
                tabList.getAttribute("data-tabs");


            var rows = panelSelector
                ? document.querySelectorAll(
                    panelSelector +
                    " [data-tab-value]"
                )
                : [];


            tabs.forEach(function (tab) {

                tab.addEventListener(
                    "click",
                    function () {

                        tabs.forEach(function (currentTab) {

                            currentTab.classList.remove(
                                "is-active"
                            );

                            currentTab.classList.remove(
                                "tab-active"
                            );

                            currentTab.classList.remove(
                                "tab"
                            );

                        });


                        tab.classList.add(
                            "is-active"
                        );

                        tab.classList.remove(
                            "tab"
                        );

                        tab.classList.remove(
                            "tab-active"
                        );


                        var value =
                            tab.getAttribute("data-tab");


                        rows.forEach(function (row) {

                            var matches =
                                value === "all" ||
                                row.getAttribute(
                                    "data-tab-value"
                                ) === value;


                            row.style.display =
                                matches
                                    ? ""
                                    : "none";

                        });

                    }
                );

            });

        });

    }


    /* ==========================================================================
     * Select All Checkboxes
     * ========================================================================== */

    function initSelectAllCheckboxes() {

        var selectAlls = document.querySelectorAll(
            "[data-select-all]"
        );


        selectAlls.forEach(function (selectAll) {

            var table =
                selectAll.closest("table");


            if (!table) {
                return;
            }


            var rowCheckboxes =
                table.querySelectorAll(
                    "tbody [data-row-check]"
                );


            selectAll.addEventListener(
                "change",
                function () {

                    rowCheckboxes.forEach(
                        function (checkbox) {

                            checkbox.checked =
                                selectAll.checked;

                        }
                    );

                }
            );


            rowCheckboxes.forEach(
                function (checkbox) {

                    checkbox.addEventListener(
                        "change",
                        function () {

                            selectAll.checked =
                                Array.prototype.every.call(
                                    rowCheckboxes,
                                    function (currentCheckbox) {
                                        return currentCheckbox.checked;
                                    }
                                );

                        }
                    );

                }
            );

        });

    }

})();


/* ==========================================================================
 * Blood Pressure Chart
 * ========================================================================== */

document.addEventListener(
    "DOMContentLoaded",
    function () {

        initBloodPressureChart();

    }
);


function initBloodPressureChart() {

    var chart = document.querySelector(
        "[data-blood-pressure-chart]"
    );

    var dataElement = document.getElementById(
        "blood-pressure-data"
    );


    if (!chart || !dataElement) {

        console.warn(
            "Blood pressure chart or data element was not found."
        );

        return;
    }


    /* ----------------------------------------------------------------------
     * Parse Blood Pressure Data
     * ---------------------------------------------------------------------- */

    var readings;


    try {

        readings = JSON.parse(
            dataElement.textContent
        );

    } catch (error) {

        console.error(
            "Unable to parse blood pressure data.",
            error
        );

        return;
    }


    if (
        !Array.isArray(readings) ||
        readings.length === 0
    ) {

        console.warn(
            "No blood pressure readings available."
        );

        return;
    }


    /* ----------------------------------------------------------------------
     * Locate SVG Elements
     * ---------------------------------------------------------------------- */

    var systolicLine =
        chart.querySelector(
            '[data-chart-line="systolic"]'
        );


    var diastolicLine =
        chart.querySelector(
            '[data-chart-line="diastolic"]'
        );


    var pointsContainer =
        chart.querySelector(
            "[data-chart-points]"
        );


    if (!systolicLine || !diastolicLine) {

        console.error(
            "Blood pressure chart lines were not found."
        );

        return;
    }


    /* ----------------------------------------------------------------------
     * Chart Dimensions
     * ---------------------------------------------------------------------- */

    var width = 1200;
    var height = 280;


    /*
     * Match the visible Y-axis:
     *
     * 180
     * 140
     * 100
     * 60
     * 20
     */

    var minValue = 20;
    var maxValue = 180;


    /* ----------------------------------------------------------------------
     * Coordinate Helpers
     * ---------------------------------------------------------------------- */

    function getX(index) {

        if (readings.length === 1) {
            return width / 2;
        }


        return (
            index /
            (readings.length - 1)
        ) * width;

    }


    function getY(value) {

        var numericValue =
            Number(value);


        if (!Number.isFinite(numericValue)) {
            return null;
        }


        var clamped =
            Math.min(
                maxValue,
                Math.max(
                    minValue,
                    numericValue
                )
            );


        return (
            height -
            (
                (
                    clamped -
                    minValue
                ) /
                (
                    maxValue -
                    minValue
                )
            ) * height
        );

    }


    /* ----------------------------------------------------------------------
     * Build Systolic Line
     * ---------------------------------------------------------------------- */

    var systolicPoints = readings
        .map(function (reading, index) {

            var y =
                getY(reading.systolic);


            if (y === null) {
                return null;
            }


            return (
                getX(index) +
                "," +
                y
            );

        })
        .filter(function (point) {
            return point !== null;
        })
        .join(" ");


    /* ----------------------------------------------------------------------
     * Build Diastolic Line
     * ---------------------------------------------------------------------- */

    var diastolicPoints = readings
        .map(function (reading, index) {

            var y =
                getY(reading.diastolic);


            if (y === null) {
                return null;
            }


            return (
                getX(index) +
                "," +
                y
            );

        })
        .filter(function (point) {
            return point !== null;
        })
        .join(" ");


    /* ----------------------------------------------------------------------
     * Apply SVG Points
     * ---------------------------------------------------------------------- */

    systolicLine.setAttribute(
        "points",
        systolicPoints
    );


    diastolicLine.setAttribute(
        "points",
        diastolicPoints
    );


    /* ----------------------------------------------------------------------
     * Force SVG Line Visibility
     * ---------------------------------------------------------------------- */

    systolicLine.setAttribute(
        "fill",
        "none"
    );

    systolicLine.setAttribute(
        "stroke",
        "var(--patient-chart-systolic)"
    );

    systolicLine.setAttribute(
        "stroke-width",
        "3"
    );

    systolicLine.setAttribute(
        "stroke-linecap",
        "round"
    );

    systolicLine.setAttribute(
        "stroke-linejoin",
        "round"
    );


    diastolicLine.setAttribute(
        "fill",
        "none"
    );

    diastolicLine.setAttribute(
        "stroke",
        "var(--patient-chart-diastolic)"
    );

    diastolicLine.setAttribute(
        "stroke-width",
        "3"
    );

    diastolicLine.setAttribute(
        "stroke-linecap",
        "round"
    );

    diastolicLine.setAttribute(
        "stroke-linejoin",
        "round"
    );


    /* ----------------------------------------------------------------------
     * Interactive Chart Points
     * ---------------------------------------------------------------------- */

    if (!pointsContainer) {
        return;
    }


    pointsContainer.innerHTML = "";


    readings.forEach(
        function (reading, index) {

            var systolic =
                Number(reading.systolic);

            var diastolic =
                Number(reading.diastolic);


            if (
                !Number.isFinite(systolic) ||
                !Number.isFinite(diastolic)
            ) {
                return;
            }


            var point =
                document.createElement("button");


            point.type = "button";

            point.className =
                "md-chart__point";


            /* --------------------------------------------------------------
             * Tooltip Direction
             * -------------------------------------------------------------- */

            if (index < 3) {

                point.classList.add(
                    "tooltip-right"
                );

            }


            if (
                index >=
                readings.length - 3
            ) {

                point.classList.add(
                    "tooltip-left"
                );

            }


            /* --------------------------------------------------------------
             * Position
             * -------------------------------------------------------------- */

            var xPercent =
                readings.length === 1
                    ? 50
                    : (
                        index /
                        (readings.length - 1)
                    ) * 100;


            var averageBloodPressure =
                (
                    systolic +
                    diastolic
                ) / 2;


            var averageY =
                getY(
                    averageBloodPressure
                );


            if (averageY === null) {
                return;
            }


            var yPercent =
                (
                    averageY /
                    height
                ) * 100;


            point.style.left =
                xPercent + "%";


            point.style.top =
                yPercent + "%";


            /* --------------------------------------------------------------
             * Accessibility
             * -------------------------------------------------------------- */

            point.setAttribute(
                "aria-label",
                reading.month +
                ": Blood pressure " +
                systolic +
                "/" +
                diastolic +
                " mmHg"
            );


            /* --------------------------------------------------------------
             * Tooltip Data
             * -------------------------------------------------------------- */

            point.dataset.tooltip =
                reading.month +
                " • " +
                systolic +
                "/" +
                diastolic +
                " mmHg";


            pointsContainer.appendChild(
                point
            );

        }
    );

}


/* ==========================================================================
 * Profile Completion Popup
 * ========================================================================== */

document.addEventListener(
    "DOMContentLoaded",
    function () {

        var popup =
            document.getElementById(
                "profileCompletionPopup"
            );


        var closeButton =
            document.getElementById(
                "profileCompletionClose"
            );


        var laterButton =
            document.getElementById(
                "profileCompletionLater"
            );


        if (!popup) {
            return;
        }


        /* ------------------------------------------------------------------
         * Dismiss Popup
         * ------------------------------------------------------------------ */

        function dismissProfilePopup() {

            fetch(
                "/api/patient/profile-popup/dismiss/",
                {
                    method: "POST",

                    headers: {
                        "X-CSRFToken":
                            getCookie("csrftoken"),

                        "Content-Type":
                            "application/json"
                    }
                }
            )
                .then(function (response) {

                    if (response.ok) {
                        popup.style.display = "none";
                    }

                })
                .catch(function (error) {

                    console.error(
                        "Unable to dismiss profile popup.",
                        error
                    );

                });

        }


        /* ------------------------------------------------------------------
         * Close Button
         * ------------------------------------------------------------------ */

        if (closeButton) {

            closeButton.addEventListener(
                "click",
                dismissProfilePopup
            );

        }


        /* ------------------------------------------------------------------
         * Maybe Later Button
         * ------------------------------------------------------------------ */

        if (laterButton) {

            laterButton.addEventListener(
                "click",
                dismissProfilePopup
            );

        }

    }
);


/* ==========================================================================
 * CSRF Cookie Helper
 * ========================================================================== */

function getCookie(name) {

    var cookies =
        document.cookie.split(";");


    for (
        var i = 0;
        i < cookies.length;
        i++
    ) {

        var cookie =
            cookies[i].trim();


        if (
            cookie.startsWith(
                name + "="
            )
        ) {

            return decodeURIComponent(
                cookie.substring(
                    name.length + 1
                )
            );

        }

    }


    return null;

}