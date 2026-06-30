const JOB_LOGGER_TIME_STEP_MINUTES = 15;
const JOB_LOGGER_MINUTES_PER_DAY = 24 * 60;

let activeDateChooserState = null;
let activeTimeDropdownState = null;

function jobLoggerDateTimePadTwo(value) {
  return String(value).padStart(2, "0");
}

function jobLoggerDateTimeSafeString(value) {
  return String(value || "");
}

function jobLoggerNormalizedDateValue(dateValue) {
  const normalizedDate = jobLoggerDateTimeSafeString(dateValue).trim();
  const dateMatch = normalizedDate.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!dateMatch) {
    return null;
  }

  const year = Number(dateMatch[1]);
  const monthIndex = Number(dateMatch[2]) - 1;
  const day = Number(dateMatch[3]);
  const localDate = new Date(year, monthIndex, day);
  if (
    localDate.getFullYear() !== year
    || localDate.getMonth() !== monthIndex
    || localDate.getDate() !== day
  ) {
    return null;
  }

  return {normalizedDate, localDate};
}

function jobLoggerDateValueFromDate(dateValue) {
  const year = String(dateValue.getFullYear()).padStart(4, "0");
  const month = jobLoggerDateTimePadTwo(dateValue.getMonth() + 1);
  const day = jobLoggerDateTimePadTwo(dateValue.getDate());
  return `${year}-${month}-${day}`;
}

function jobLoggerCurrentDetroitDateValue() {
  const dateParts = new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "America/Detroit",
    year: "numeric",
  }).formatToParts(new Date());
  const partValues = Object.fromEntries(dateParts.map((part) => [part.type, part.value]));
  if (!partValues.year || !partValues.month || !partValues.day) {
    return jobLoggerDateValueFromDate(new Date());
  }

  return `${partValues.year}-${partValues.month}-${partValues.day}`;
}

function jobLoggerParseTimeToMinutes(timeValue) {
  const normalizedTimeValue = jobLoggerDateTimeSafeString(timeValue).trim().toLowerCase().replace(/\s+/g, " ");
  const twelveHourMatch = normalizedTimeValue.match(/^(\d{1,2}):(\d{2})\s*([ap])\.?m\.?$/);
  if (twelveHourMatch) {
    const hour = Number(twelveHourMatch[1]);
    const minute = Number(twelveHourMatch[2]);
    const period = twelveHourMatch[3];
    if (hour < 1 || hour > 12 || minute < 0 || minute > 59) {
      return null;
    }

    const hour24 = period === "a"
      ? (hour === 12 ? 0 : hour)
      : (hour === 12 ? 12 : hour + 12);
    return hour24 * 60 + minute;
  }

  const twentyFourHourMatch = normalizedTimeValue.match(/^(\d{1,2}):(\d{2})$/);
  if (!twentyFourHourMatch) {
    return null;
  }

  const hour = Number(twentyFourHourMatch[1]);
  const minute = Number(twentyFourHourMatch[2]);
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    return null;
  }

  return hour * 60 + minute;
}

function jobLoggerFormatMinutesAsTime(totalMinutes) {
  const normalizedTotalMinutes = (
    (totalMinutes % JOB_LOGGER_MINUTES_PER_DAY) + JOB_LOGGER_MINUTES_PER_DAY
  ) % JOB_LOGGER_MINUTES_PER_DAY;
  const hour24 = Math.floor(normalizedTotalMinutes / 60);
  const minute = normalizedTotalMinutes % 60;
  const hour12 = hour24 % 12 || 12;
  const period = hour24 < 12 ? "am" : "pm";
  return `${hour12}:${jobLoggerDateTimePadTwo(minute)} ${period}`;
}

function jobLoggerCommitInputValue(inputElement, value) {
  inputElement.value = value;
  inputElement.dispatchEvent(new Event("input", {bubbles: true}));
  inputElement.dispatchEvent(new Event("change", {bubbles: true}));
}

function jobLoggerPositionFloatingElement(anchorElement, floatingElement) {
  const anchorRect = anchorElement.getBoundingClientRect();
  const viewportGap = 8;
  const maxWidth = Math.max(anchorRect.width, 220);
  floatingElement.style.minWidth = `${Math.min(maxWidth, window.innerWidth - viewportGap * 2)}px`;
  floatingElement.style.maxWidth = `${window.innerWidth - viewportGap * 2}px`;

  const floatingRect = floatingElement.getBoundingClientRect();
  const spaceBelow = window.innerHeight - anchorRect.bottom - viewportGap;
  const spaceAbove = anchorRect.top - viewportGap;
  const top = spaceBelow >= floatingRect.height || spaceBelow >= spaceAbove
    ? Math.min(anchorRect.bottom + viewportGap, window.innerHeight - floatingRect.height - viewportGap)
    : Math.max(viewportGap, anchorRect.top - floatingRect.height - viewportGap);
  const left = Math.min(
    Math.max(viewportGap, anchorRect.left),
    Math.max(viewportGap, window.innerWidth - floatingRect.width - viewportGap),
  );

  floatingElement.style.left = `${left}px`;
  floatingElement.style.top = `${Math.max(viewportGap, top)}px`;
}

function jobLoggerCloseDateChooser({restoreFocus = false} = {}) {
  if (!activeDateChooserState) {
    return;
  }

  const {inputElement, popoverElement} = activeDateChooserState;
  popoverElement.remove();
  inputElement.removeAttribute("aria-expanded");
  if (restoreFocus) {
    inputElement.focus({preventScroll: true});
  }
  activeDateChooserState = null;
}

function jobLoggerRenderDateChooser() {
  if (!activeDateChooserState) {
    return;
  }

  const {
    inputElement,
    popoverElement,
    selectedDateValue,
    visibleMonthDate,
  } = activeDateChooserState;
  const todayValue = jobLoggerCurrentDetroitDateValue();
  const monthTitle = new Intl.DateTimeFormat("en-US", {
    month: "long",
    year: "numeric",
  }).format(visibleMonthDate);
  const firstOfMonth = new Date(visibleMonthDate.getFullYear(), visibleMonthDate.getMonth(), 1);
  const firstVisibleDay = new Date(firstOfMonth);
  firstVisibleDay.setDate(firstVisibleDay.getDate() - firstVisibleDay.getDay());

  const header = document.createElement("div");
  header.className = "date-chooser-header";

  const previousMonthButton = document.createElement("button");
  previousMonthButton.type = "button";
  previousMonthButton.className = "date-chooser-month-button";
  previousMonthButton.setAttribute("aria-label", "Previous month");
  previousMonthButton.textContent = "<";
  previousMonthButton.addEventListener("click", () => {
    activeDateChooserState.visibleMonthDate = new Date(
      visibleMonthDate.getFullYear(),
      visibleMonthDate.getMonth() - 1,
      1,
    );
    jobLoggerRenderDateChooser();
  });

  const title = document.createElement("h2");
  title.className = "date-chooser-title";
  title.textContent = monthTitle;

  const nextMonthButton = document.createElement("button");
  nextMonthButton.type = "button";
  nextMonthButton.className = "date-chooser-month-button";
  nextMonthButton.setAttribute("aria-label", "Next month");
  nextMonthButton.textContent = ">";
  nextMonthButton.addEventListener("click", () => {
    activeDateChooserState.visibleMonthDate = new Date(
      visibleMonthDate.getFullYear(),
      visibleMonthDate.getMonth() + 1,
      1,
    );
    jobLoggerRenderDateChooser();
  });
  header.append(previousMonthButton, title, nextMonthButton);

  const weekdayRow = document.createElement("div");
  weekdayRow.className = "date-chooser-weekdays";
  for (const weekdayLabel of ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]) {
    const weekdayElement = document.createElement("span");
    weekdayElement.textContent = weekdayLabel;
    weekdayRow.append(weekdayElement);
  }

  const grid = document.createElement("div");
  grid.className = "date-chooser-grid";
  for (let dayOffset = 0; dayOffset < 42; dayOffset += 1) {
    const dayDate = new Date(firstVisibleDay);
    dayDate.setDate(firstVisibleDay.getDate() + dayOffset);
    const dayDateValue = jobLoggerDateValueFromDate(dayDate);
    const dayButton = document.createElement("button");
    dayButton.type = "button";
    dayButton.className = "date-chooser-day";
    dayButton.textContent = String(dayDate.getDate());
    dayButton.dataset.dateValue = dayDateValue;
    dayButton.setAttribute("aria-label", dayDateValue);
    dayButton.classList.toggle("is-outside-month", dayDate.getMonth() !== visibleMonthDate.getMonth());
    dayButton.classList.toggle("is-selected", dayDateValue === selectedDateValue);
    dayButton.classList.toggle("is-today", dayDateValue === todayValue);
    dayButton.setAttribute("aria-pressed", dayDateValue === selectedDateValue ? "true" : "false");
    dayButton.addEventListener("click", () => {
      activeDateChooserState.selectedDateValue = dayDateValue;
      if (dayDate.getMonth() !== visibleMonthDate.getMonth()) {
        activeDateChooserState.visibleMonthDate = new Date(dayDate.getFullYear(), dayDate.getMonth(), 1);
      }
      jobLoggerRenderDateChooser();
    });
    grid.append(dayButton);
  }

  const footer = document.createElement("div");
  footer.className = "date-chooser-footer";

  const todayButton = document.createElement("button");
  todayButton.type = "button";
  todayButton.className = "date-chooser-link-button";
  todayButton.textContent = "Today";
  todayButton.addEventListener("click", () => {
    const currentTodayValue = jobLoggerCurrentDetroitDateValue();
    jobLoggerCommitInputValue(inputElement, currentTodayValue);
    jobLoggerCloseDateChooser({restoreFocus: true});
  });

  const footerSpacer = document.createElement("span");
  footerSpacer.className = "date-chooser-footer-spacer";

  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.className = "date-chooser-link-button";
  cancelButton.textContent = "Cancel";
  cancelButton.addEventListener("click", () => {
    jobLoggerCloseDateChooser({restoreFocus: true});
  });

  const setButton = document.createElement("button");
  setButton.type = "button";
  setButton.className = "date-chooser-link-button";
  setButton.textContent = "Set";
  setButton.addEventListener("click", () => {
    jobLoggerCommitInputValue(inputElement, activeDateChooserState.selectedDateValue);
    jobLoggerCloseDateChooser({restoreFocus: true});
  });
  footer.append(todayButton, footerSpacer, cancelButton, setButton);

  popoverElement.replaceChildren(header, weekdayRow, grid, footer);
  jobLoggerPositionFloatingElement(inputElement, popoverElement);

  const selectedButton = popoverElement.querySelector(".date-chooser-day.is-selected");
  if (selectedButton && selectedDateValue === todayValue) {
    selectedButton.setAttribute("aria-current", "date");
  }
}

function jobLoggerOpenDateChooser(inputElement) {
  if (!inputElement || inputElement.disabled) {
    return;
  }

  jobLoggerCloseTimeDropdown();
  jobLoggerCloseDateChooser();

  const currentDateValue = jobLoggerNormalizedDateValue(inputElement.value)
    ? inputElement.value
    : jobLoggerCurrentDetroitDateValue();
  const currentDateInfo = jobLoggerNormalizedDateValue(currentDateValue);
  if (!currentDateInfo) {
    return;
  }

  const popoverElement = document.createElement("div");
  popoverElement.className = "date-chooser-popover";
  popoverElement.setAttribute("role", "dialog");
  popoverElement.setAttribute("aria-modal", "false");
  popoverElement.setAttribute("aria-label", "Choose date");
  document.body.append(popoverElement);

  activeDateChooserState = {
    inputElement,
    popoverElement,
    selectedDateValue: currentDateInfo.normalizedDate,
    visibleMonthDate: new Date(currentDateInfo.localDate.getFullYear(), currentDateInfo.localDate.getMonth(), 1),
  };
  inputElement.setAttribute("aria-expanded", "true");
  jobLoggerRenderDateChooser();
}

function jobLoggerCloseTimeDropdown({restoreFocus = false} = {}) {
  if (!activeTimeDropdownState) {
    return;
  }

  const {inputElement, dropdownElement} = activeTimeDropdownState;
  dropdownElement.remove();
  inputElement.removeAttribute("aria-expanded");
  if (restoreFocus) {
    inputElement.focus({preventScroll: true});
  }
  activeTimeDropdownState = null;
}

function jobLoggerOpenTimeDropdown(inputElement) {
  if (!inputElement || inputElement.disabled || inputElement.readOnly) {
    return;
  }

  jobLoggerCloseDateChooser();
  jobLoggerCloseTimeDropdown();

  const selectedMinutes = jobLoggerParseTimeToMinutes(inputElement.value);
  const roundedSelectedMinutes = selectedMinutes === null
    ? 0
    : Math.round(selectedMinutes / JOB_LOGGER_TIME_STEP_MINUTES) * JOB_LOGGER_TIME_STEP_MINUTES;
  const normalizedSelectedMinutes = (
    (roundedSelectedMinutes % JOB_LOGGER_MINUTES_PER_DAY) + JOB_LOGGER_MINUTES_PER_DAY
  ) % JOB_LOGGER_MINUTES_PER_DAY;

  const dropdownElement = document.createElement("div");
  dropdownElement.className = "time-dropdown-popover";
  dropdownElement.setAttribute("role", "listbox");
  dropdownElement.setAttribute("aria-label", "Choose time");
  dropdownElement.tabIndex = -1;

  let selectedButton = null;
  for (let minuteValue = 0; minuteValue < JOB_LOGGER_MINUTES_PER_DAY; minuteValue += JOB_LOGGER_TIME_STEP_MINUTES) {
    const optionButton = document.createElement("button");
    optionButton.type = "button";
    optionButton.className = "time-dropdown-option";
    optionButton.setAttribute("role", "option");
    optionButton.dataset.timeMinutes = String(minuteValue);
    optionButton.textContent = jobLoggerFormatMinutesAsTime(minuteValue);
    optionButton.setAttribute("aria-selected", minuteValue === normalizedSelectedMinutes ? "true" : "false");
    if (minuteValue === normalizedSelectedMinutes) {
      optionButton.classList.add("is-selected");
      selectedButton = optionButton;
    }
    optionButton.addEventListener("mousedown", (event) => {
      event.preventDefault();
    });
    optionButton.addEventListener("click", () => {
      jobLoggerCommitInputValue(inputElement, jobLoggerFormatMinutesAsTime(minuteValue));
      jobLoggerCloseTimeDropdown({restoreFocus: true});
    });
    dropdownElement.append(optionButton);
  }

  document.body.append(dropdownElement);
  activeTimeDropdownState = {inputElement, dropdownElement};
  inputElement.setAttribute("aria-expanded", "true");
  jobLoggerPositionFloatingElement(inputElement, dropdownElement);
  if (selectedButton) {
    selectedButton.scrollIntoView({block: "center"});
  }
}

function jobLoggerInitializeDateInputs(root = document) {
  const dateInputs = root.querySelectorAll("[data-date-chooser-input]");
  for (const dateInput of dateInputs) {
    if (dateInput.dataset.dateChooserInitialized === "true") {
      continue;
    }

    dateInput.dataset.dateChooserInitialized = "true";
    try {
      dateInput.type = "text";
    } catch (error) {
      // Some browsers reject type changes for specialized inputs; the picker
      // still opens through pointer/keyboard event handlers below.
    }
    dateInput.readOnly = true;
    dateInput.inputMode = "none";
    dateInput.autocomplete = "off";
    dateInput.setAttribute("aria-haspopup", "dialog");
    dateInput.addEventListener("click", (event) => {
      event.preventDefault();
      jobLoggerOpenDateChooser(dateInput);
    });
    dateInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
        event.preventDefault();
        jobLoggerOpenDateChooser(dateInput);
      }
    });
  }
}

function jobLoggerInitializeTimeInputs(root = document) {
  const timeInputs = root.querySelectorAll(".time-field-input");
  for (const timeInput of timeInputs) {
    if (timeInput.dataset.timeDropdownInitialized === "true") {
      continue;
    }

    timeInput.dataset.timeDropdownInitialized = "true";
    timeInput.setAttribute("aria-haspopup", "listbox");
    timeInput.addEventListener("focus", () => {
      jobLoggerOpenTimeDropdown(timeInput);
    });
    timeInput.addEventListener("click", () => {
      jobLoggerOpenTimeDropdown(timeInput);
    });
    timeInput.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        jobLoggerOpenTimeDropdown(timeInput);
      }
    });
  }
}

function jobLoggerInitializeDateTimeControls(root = document) {
  jobLoggerInitializeDateInputs(root);
  jobLoggerInitializeTimeInputs(root);
}

document.addEventListener("mousedown", (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }

  if (
    activeDateChooserState
    && event.target !== activeDateChooserState.inputElement
    && !activeDateChooserState.popoverElement.contains(event.target)
  ) {
    jobLoggerCloseDateChooser();
  }

  if (
    activeTimeDropdownState
    && event.target !== activeTimeDropdownState.inputElement
    && !activeTimeDropdownState.dropdownElement.contains(event.target)
  ) {
    jobLoggerCloseTimeDropdown();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    jobLoggerCloseDateChooser({restoreFocus: true});
    jobLoggerCloseTimeDropdown({restoreFocus: true});
  }
});

window.addEventListener("resize", () => {
  if (activeDateChooserState) {
    jobLoggerPositionFloatingElement(activeDateChooserState.inputElement, activeDateChooserState.popoverElement);
  }
  if (activeTimeDropdownState) {
    jobLoggerPositionFloatingElement(activeTimeDropdownState.inputElement, activeTimeDropdownState.dropdownElement);
  }
});

window.JobLoggerDateTimeControls = {
  initialize: jobLoggerInitializeDateTimeControls,
  openDateChooser: jobLoggerOpenDateChooser,
  openTimeDropdown: jobLoggerOpenTimeDropdown,
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => jobLoggerInitializeDateTimeControls(), {once: true});
} else {
  jobLoggerInitializeDateTimeControls();
}
