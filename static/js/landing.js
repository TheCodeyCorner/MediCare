document.addEventListener("DOMContentLoaded", () => {

  const grid = document.getElementById("doctorGrid");
  const searchInput = document.getElementById("doctorSearch");
  const emptyState = document.getElementById("doctorsEmpty");
  const loadMoreContainer = document.getElementById("doctorsLoadMore");
  const loadMoreButton = document.getElementById("loadMoreDoctors");

  const filterButtons = document.querySelectorAll(
    ".filter-row .pill"
  );

  if (!grid) return;


  /* =====================================================
     SETTINGS
     ===================================================== */

  const DOCTORS_PER_LOAD = 6;


  /* =====================================================
     STATE
     ===================================================== */

  let activeFilter = "all";
  let visibleLimit = DOCTORS_PER_LOAD;


  /* =====================================================
     NORMALIZE TEXT
     ===================================================== */

  function normalize(value) {
    return String(value || "")
      .toLowerCase()
      .trim();
  }


  /* =====================================================
     GET DOCTOR CARDS
     
     Queried every time so newly injected doctors
     are automatically detected.
     ===================================================== */

  function getDoctorCards() {
    return Array.from(
      grid.querySelectorAll(".doctor-card")
    );
  }


  /* =====================================================
     CHECK DOCTOR MATCH
     
     Uses department instead of specialty.
     Expected HTML:

     data-department="cardiology"
     data-name="Dr. John Doe"
     data-search="Dr. John Doe cardiologist heart"
     ===================================================== */

  function doctorMatches(card) {

    const doctorDepartment =
      normalize(card.dataset.department);

    const doctorName =
      normalize(card.dataset.name);

    const doctorSearchData =
      normalize(card.dataset.search);

    const searchTerm =
      normalize(
        searchInput
          ? searchInput.value
          : ""
      );


    /* ---------------------------------------------
       Department
       --------------------------------------------- */

    const matchesDepartment =
      activeFilter === "all" ||
      doctorDepartment === activeFilter;


    /* ---------------------------------------------
       Search
       --------------------------------------------- */

    const matchesSearch =
      !searchTerm ||
      doctorName.includes(searchTerm) ||
      doctorDepartment.includes(searchTerm) ||
      doctorSearchData.includes(searchTerm);


    return (
      matchesDepartment &&
      matchesSearch
    );
  }


  /* =====================================================
     UPDATE DOCTORS
     
     Handles:
       - department filtering
       - search
       - pagination
       - empty state
       - load more
     ===================================================== */

  function filterDoctors() {

    const cards = getDoctorCards();


    /* ---------------------------------------------
       Find matching doctors
       --------------------------------------------- */

    const matchingCards = cards.filter(
      doctorMatches
    );


    /* ---------------------------------------------
       Show only doctors within visible limit
       --------------------------------------------- */

    matchingCards.forEach((card, index) => {

      const shouldShow =
        index < visibleLimit;

      card.classList.toggle(
        "is-hidden",
        !shouldShow
      );

    });


    /* ---------------------------------------------
       Hide non-matching doctors
       --------------------------------------------- */

    cards.forEach(card => {

      if (!matchingCards.includes(card)) {

        card.classList.add(
          "is-hidden"
        );

      }

    });


    /* =================================================
       EMPTY STATE
       ================================================= */

    if (emptyState) {

      const noResults =
        matchingCards.length === 0;

      emptyState.hidden =
        !noResults;

      emptyState.classList.toggle(
        "visible",
        noResults
      );

    }


    /* =================================================
       LOAD MORE
       ================================================= */

    const hasMore =
      matchingCards.length > visibleLimit;


    if (loadMoreContainer) {

      loadMoreContainer.hidden =
        !hasMore;

    }


    if (loadMoreButton) {

      loadMoreButton.disabled =
        !hasMore;

    }
  }


  /* =====================================================
     LOAD MORE DOCTORS
     ===================================================== */

  function loadMoreDoctors() {

    const previousLimit =
      visibleLimit;


    visibleLimit +=
      DOCTORS_PER_LOAD;


    filterDoctors();


    /* ---------------------------------------------
       Find the first newly revealed doctor
       --------------------------------------------- */

    const matchingCards =
      getDoctorCards().filter(
        doctorMatches
      );


    const firstNewCard =
      matchingCards[previousLimit];


    if (firstNewCard) {

      firstNewCard.scrollIntoView({
        behavior: "smooth",
        block: "center"
      });

    }
  }


  /* =====================================================
     LOAD MORE BUTTON
     ===================================================== */

  if (loadMoreButton) {

    loadMoreButton.addEventListener(
      "click",
      loadMoreDoctors
    );

  }


  /* =====================================================
     DEPARTMENT FILTER BUTTONS
     ===================================================== */

  filterButtons.forEach(button => {

    button.addEventListener("click", () => {

      /* ---------------------------------------------
         Read the selected department
         --------------------------------------------- */

      const selectedDepartment =
        normalize(button.dataset.filter);


      /* ---------------------------------------------
         Store selected department
         --------------------------------------------- */

      activeFilter = selectedDepartment;


      /* ---------------------------------------------
         Reset pagination
         --------------------------------------------- */

      visibleLimit = DOCTORS_PER_LOAD;


      /* ---------------------------------------------
         Update active pill
         --------------------------------------------- */

      filterButtons.forEach(pill => {

        const isSelected =
          pill === button;


        pill.classList.toggle(
          "active",
          isSelected
        );


        pill.classList.toggle(
          "pill--active",
          isSelected
        );


        pill.setAttribute(
          "aria-pressed",
          String(isSelected)
        );

      });


      /* ---------------------------------------------
         Filter doctors
         --------------------------------------------- */

      filterDoctors();

    });

  });


  /* =====================================================
     SERVICE → DOCTOR DEPARTMENT
     ===================================================== */

  document.addEventListener("click", (event) => {

    const service = event.target.closest(
      ".service-card[data-department]"
    );

    if (!service) return;

    const department =
      normalize(service.dataset.department);

    if (!department) return;

    /* ---------------------------------------------
       Find matching doctor pill
       --------------------------------------------- */

    const matchingPill = Array.from(filterButtons).find(
      pill =>
        normalize(pill.dataset.filter) === department
    );

    if (!matchingPill) {
      console.warn(
        `No doctor filter found for: ${department}`
      );
      return;
    }

    /* ---------------------------------------------
       Activate the pill
       --------------------------------------------- */

    activeFilter = department;

    visibleLimit = DOCTORS_PER_LOAD;

    filterButtons.forEach(pill => {

      const isSelected =
        pill === matchingPill;

      pill.classList.toggle(
        "active",
        isSelected
      );

      pill.classList.toggle(
        "pill--active",
        isSelected
      );

      pill.setAttribute(
        "aria-pressed",
        String(isSelected)
      );

    });

    /* ---------------------------------------------
       Apply doctor filter
       --------------------------------------------- */

    filterDoctors();

  });


  /* =====================================================
     SEARCH
     ===================================================== */

  if (searchInput) {

    searchInput.addEventListener(
      "input",
      () => {

        /* Reset pagination */

        visibleLimit =
          DOCTORS_PER_LOAD;


        filterDoctors();

      }
    );

  }


  /* =====================================================
     INITIALIZE
     ===================================================== */

  filterDoctors();


  /* =====================================================
     REFRESH DOCTORS
     
     Call this after adding doctors dynamically.

     Example:

       doctorGrid.insertAdjacentHTML(
         "beforeend",
         doctorHTML
       );

       window.refreshDoctors();
     ===================================================== */

  window.refreshDoctors = function () {

    visibleLimit =
      DOCTORS_PER_LOAD;

    filterDoctors();

  };


  /* =====================================================
     SHOW ALL DOCTORS
     ===================================================== */

  window.showAllDoctors = function () {

    const cards =
      getDoctorCards();

    visibleLimit =
      cards.length;

    filterDoctors();

  };

});