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




/* ==========================================================================
 * Patient Messaging Helpers — Global Scope
 * ========================================================================== */


function formatMessageTime(sentAt) {
    if (!sentAt) return "";

    const date = new Date(sentAt);

    if (Number.isNaN(date.getTime())) return "";

    return date.toLocaleString("en-IN", {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
        hour12: true
    });
}

function appendMessage(thread, message, currentUserId) {
    if (!thread || !message) return;

    if (message.m_id != null) {
        const messageId = String(message.m_id);

        const alreadyRendered = Array.from(
            thread.querySelectorAll("[data-message-id]")
        ).some(function (element) {
            return element.dataset.messageId === messageId;
        });

        if (alreadyRendered) return;
    }

    const emptyState = thread.querySelector(
        ".patient-messages-empty-thread"
    );

    if (emptyState) emptyState.remove();

    const mine =
        String(message.sender_id) === String(currentUserId);

    const article = document.createElement("article");

    article.className =
        "patient-messages-message " +
        (mine
            ? "patient-messages-message--mine"
            : "patient-messages-message--theirs");

    if (message.m_id != null) {
        article.dataset.messageId = String(message.m_id);
    }

    const bubble = document.createElement("div");
    bubble.className = "patient-messages-bubble";

    const paragraph = document.createElement("p");
    paragraph.textContent = message.message_content || "";
    bubble.appendChild(paragraph);

    const timestamp = message.sent_at || message.created_at;
    const formattedTime = formatMessageTime(timestamp);

    if (formattedTime) {
        const time = document.createElement("time");
        time.className = "patient-messages-message__time";
        time.dateTime = timestamp;
        time.textContent = formattedTime;
        bubble.appendChild(time);
    }

    article.appendChild(bubble);
    thread.appendChild(article);

    enforceMessageLimit(thread, 20);
    scrollChatToLatest(thread);
}


function scrollChatToLatest(thread) {
    if (!thread || thread.hidden) return;

    thread.scrollTop = thread.scrollHeight;
}


function enforceMessageLimit(thread, limit = 20) {
    if (!thread) return;

    const messages = thread.querySelectorAll(
        ".patient-messages-message"
    );

    const excess = messages.length - limit;

    for (let i = 0; i < excess; i++) {
        messages[i].remove();
    }
}


/* ==========================================================================
 * Patient Messaging Initialization
 * ========================================================================== */

document.addEventListener("DOMContentLoaded", function () {
    "use strict";

    const form = document.querySelector("[data-message-form]");
    const chatIdInput = document.querySelector("[data-composer-chat-id]");
    const messageInput = document.getElementById("patient-message-input");

    if (!form || !chatIdInput || !messageInput) {
        return;
    }

    // Prevent duplicate event handlers.
    if (form.dataset.messagingBound === "true") {
        return;
    }

    form.dataset.messagingBound = "true";

    const sendButton = form.querySelector('button[type="submit"]');
    const readonlyNote = document.querySelector("[data-readonly-note]");
    const composerHelp = document.querySelector("[data-composer-help]");

    const activeName = document.querySelector("[data-active-name]");
    const activeSubtitle = document.querySelector("[data-active-subtitle]");
    const activeAvatar = document.querySelector("[data-active-avatar]");
    const activeStatus = document.querySelector("[data-active-status]");
    const activeContext = document.querySelector("[data-active-context]");

    const appointmentDetails = document.querySelector(
        "[data-details-appointment]"
    );

    const announcementsDetails = document.querySelector(
        "[data-details-announcements]"
    );

    const supportDetails = document.querySelector("[data-details-support]");
    const detailDoctor = document.querySelector("[data-detail-doctor]");

    const detailAppointment = document.querySelector(
        "[data-detail-appointment]"
    );

    const detailStatus = document.querySelector("[data-detail-status]");

    const conversationButtons = Array.from(
        document.querySelectorAll("[data-chat-id][data-chat-type]")
    );

    const threads = Array.from(
        document.querySelectorAll("[data-chat-thread]")
    );

    const csrfInput = form.querySelector(
        'input[name="csrfmiddlewaretoken"]'
    );

    const csrfToken = csrfInput
        ? csrfInput.value
        : getCookie("csrftoken");

    let activeChat = null;
    let isSubmitting = false;
    let isRefreshingMessages = false;

    const uuidPattern =
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;


    function setText(element, value) {
        if (element) {
            element.textContent = value || "";
        }
    }


    function showElement(element, visible) {
        if (element) {
            element.hidden = !visible;
        }
    }


    function getThreadId(chat) {
        return chat.dataset.chatId || "";
    }


    function getChatType(chat) {
        return chat.dataset.chatType || "";
    }


    function getChatName(chat) {
        const title = chat.querySelector(
            ".patient-messages-conversation__top strong"
        );

        return chat.dataset.chatName ||
            title?.textContent.trim() ||
            "Conversation";
    }


    function getChatCanChat(chat) {
        return chat.dataset.chatCanChat === "true" ||
            chat.dataset.canChat === "true";
    }


    function getChatStatus(chat) {
        const meta = chat.querySelector(
            ".patient-messages-conversation__meta"
        );

        if (!getChatCanChat(chat)) {
            return meta?.textContent.trim() || "Read only";
        }

        return getChatType(chat) === "support"
            ? "Customer Care"
            : "Messaging available";
    }


    function updateComposer(chat) {
        const type = getChatType(chat);
        const canChat = getChatCanChat(chat);

        const showComposer =
            canChat &&
            (type === "support" || type === "appointment");

        showElement(form, showComposer);

        if (sendButton) {
            sendButton.disabled = !showComposer || isSubmitting;
        }

        messageInput.disabled = !showComposer;

        messageInput.placeholder = type === "support"
            ? "Message Customer Care..."
            : "Write a message...";

        showElement(readonlyNote, !showComposer);
        showElement(composerHelp, showComposer);

        if (readonlyNote) {
            readonlyNote.textContent = type === "announcements"
                ? "Announcements are read-only. You cannot reply here."
                : "This conversation is read-only. You can still view previous messages.";
        }
    }


    function updateDetails(chat) {
        const type = getChatType(chat);
        const isAppointment = type === "appointment";

        showElement(appointmentDetails, isAppointment);
        showElement(announcementsDetails, type === "announcements");
        showElement(supportDetails, type === "support");

        if (isAppointment) {
            setText(
                detailDoctor,
                chat.dataset.doctorName || getChatName(chat)
            );

            setText(
                detailAppointment,
                chat.dataset.appointmentLabel || "Appointment conversation"
            );

            setText(detailStatus, getChatStatus(chat));
        }
    }


    function selectConversation(chat) {
        if (!chat) return;

        activeChat = chat;

        const chatId = getThreadId(chat);
        const type = getChatType(chat);
        const name = getChatName(chat);

        conversationButtons.forEach(function (button) {
            const selected = button === chat;

            button.classList.toggle("is-active", selected);
            button.setAttribute("aria-pressed", String(selected));
        });

        threads.forEach(function (thread) {
            thread.hidden = thread.dataset.chatThread !== chatId;
        });

        chatIdInput.value = chatId;

        setText(activeName, name);

        setText(
            activeSubtitle,
            chat.dataset.chatSubtitle ||
                (type === "appointment"
                    ? "Appointment conversation"
                    : type === "support"
                        ? "Medicare Support"
                        : "Official updates from Medicare")
        );

        setText(
            activeAvatar,
            chat.dataset.chatAvatar || name.slice(0, 1).toUpperCase()
        );

        setText(activeStatus, getChatStatus(chat));

        setText(
            activeContext,
            chat.dataset.chatContext ||
                "Messages and information for this conversation."
        );

        updateComposer(chat);
        updateDetails(chat);

        const visibleThread = threads.find(function (thread) {
            return thread.dataset.chatThread === chatId;
        });

        if (visibleThread) {
            visibleThread.scrollTop = visibleThread.scrollHeight;
        }
    }


    /* ----------------------------------------------------------------------
     * Refresh Messages
     * ---------------------------------------------------------------------- */

    async function refreshActiveMessages() {
        if (isRefreshingMessages || !activeChat) return;

        const chatId = getThreadId(activeChat);
        const type = getChatType(activeChat);

        let endpoint;

        if (type === "support") {
            endpoint = "/patient/messages/support/";
        } else if (type === "appointment" && uuidPattern.test(chatId)) {
            endpoint =
                `/patient/messages/${encodeURIComponent(chatId)}/`;
        } else {
            return;
        }

        const thread = threads.find(
            item => item.dataset.chatThread === chatId
        );

        if (!thread) return;

        isRefreshingMessages = true;

        try {
            const response = await fetch(endpoint, {
                method: "GET",
                credentials: "same-origin",
                headers: {
                    "Accept": "application/json"
                },
                cache: "no-store"
            });

            if (!response.ok) {
                console.error(
                    "Message refresh failed:",
                    response.status
                );
                return;
            }

            const result = await response.json();

            const currentUserId = document.querySelector(
                "[data-current-user-id]"
            )?.dataset.currentUserId;

            (result.messages || []).forEach(function (message) {
                appendMessage(thread, message, currentUserId);
            });

        } catch (error) {
            console.debug(
                "Message refresh temporarily failed:",
                error
            );
        } finally {
            isRefreshingMessages = false;
        }
    }


    window.setInterval(function () {
        if (!document.hidden) {
            refreshActiveMessages();
        }
    }, 4000);

    document.addEventListener("visibilitychange", function () {
        if (!document.hidden) {
            refreshActiveMessages();
        }
    });


    /* ----------------------------------------------------------------------
     * Conversation Selection
     * ---------------------------------------------------------------------- */

    conversationButtons.forEach(function (chat) {
        chat.addEventListener("click", function () {
            selectConversation(chat);
        });
    });


    /* ----------------------------------------------------------------------
     * Conversation Search
     * ---------------------------------------------------------------------- */

    const searchInput = document.querySelector(
        "[data-conversation-search]"
    );

    if (searchInput) {
        searchInput.addEventListener("input", function () {
            const query = searchInput.value.trim().toLowerCase();

            conversationButtons.forEach(function (chat) {
                chat.hidden = !chat.textContent.toLowerCase().includes(query);
            });
        });
    }


    /* ----------------------------------------------------------------------
     * All / Unread Filters
     * ---------------------------------------------------------------------- */

    const filterButtons = document.querySelectorAll(
        "[data-message-filter]"
    );

    filterButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            const filter = button.dataset.messageFilter;

            filterButtons.forEach(function (item) {
                item.classList.toggle("is-active", item === button);
            });

            conversationButtons.forEach(function (chat) {
                chat.hidden =
                    filter === "unread" &&
                    chat.dataset.unread !== "true";
            });
        });
    });


    /* ----------------------------------------------------------------------
     * Send Message
     * ---------------------------------------------------------------------- */

    form.addEventListener("submit", async function (event) {
        event.preventDefault();

        if (isSubmitting) return;

        if (!activeChat) {
            alert("Select a conversation first.");
            return;
        }

        const chatId = getThreadId(activeChat);
        const type = getChatType(activeChat);
        const messageContent = messageInput.value.trim();

        if (!messageContent) {
            messageInput.focus();
            return;
        }

        if (!getChatCanChat(activeChat)) {
            alert("This conversation is read-only.");
            return;
        }

        let endpoint;

        if (type === "support") {
            endpoint = "/patient/messages/support/send/";
        } else if (type === "appointment") {
            if (!uuidPattern.test(chatId)) {
                alert("The appointment ID is missing or invalid.");
                return;
            }

            endpoint =
                `/patient/messages/${encodeURIComponent(chatId)}/send/`;
        } else {
            alert("This conversation does not support sending messages.");
            return;
        }

        const submittedText = messageContent;

        isSubmitting = true;

        if (sendButton) {
            sendButton.disabled = true;
        }

        messageInput.disabled = true;

        try {
            const response = await fetch(endpoint, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken || "",
                    "Accept": "application/json"
                },
                body: JSON.stringify({
                    message_content: submittedText
                })
            });

            const result = await response.json().catch(() => ({}));

            if (!response.ok) {
                throw new Error(
                    result.error ||
                    result.detail ||
                    `Message sending failed (HTTP ${response.status}).`
                );
            }

            if (!result.message) {
                throw new Error(
                    "The server returned no message data."
                );
            }

            if (messageInput.value.trim() === submittedText) {
                messageInput.value = "";
            }

            const thread = threads.find(
                item => item.dataset.chatThread === chatId
            );

            const currentUserId = document.querySelector(
                "[data-current-user-id]"
            )?.dataset.currentUserId;

            appendMessage(thread, result.message, currentUserId);

        } catch (error) {
            console.error(
                "Patient message submission failed:",
                error
            );

            alert(error.message || "Unable to send your message.");

        } finally {
            isSubmitting = false;

            if (activeChat) {
                updateComposer(activeChat);
            } else {
                if (sendButton) sendButton.disabled = false;
                messageInput.disabled = false;
            }
        }
    });


    /* ----------------------------------------------------------------------
     * Initial Conversation
     * ---------------------------------------------------------------------- */

    const initiallySelected = conversationButtons.find(function (chat) {
        return chat.classList.contains("is-active");
    });

    if (initiallySelected) {
        selectConversation(initiallySelected);
    } else if (conversationButtons.length > 0) {
        selectConversation(conversationButtons[0]);
    }
});
