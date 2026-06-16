const TIME_STEP_MINUTES = 15;

function normalizeDateValue(dateValue) {
  const parsedDate = dateValue.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!parsedDate) {
    return null;
  }

  const [, yearText, monthText, dayText] = parsedDate;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  if (!year || !month || !day) {
    return null;
  }

  const date = new Date(year, month - 1, day);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return {date, year, month, day};
}

function formatDateValue(date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function addDaysToDateString(dateValue, dayDelta) {
  const parsed = normalizeDateValue(dateValue);
  if (!parsed) {
    return dateValue;
  }

  const nextDate = parsed.date;
  nextDate.setDate(nextDate.getDate() + dayDelta);
  return formatDateValue(nextDate);
}

function padTwo(value) {
  return String(value).padStart(2, "0");
}

function adjustTimeField(timeFieldName, dateFieldName, deltaMinutes) {
  const timeInput = document.querySelector(`input[name="${timeFieldName}"]`);
  const dateInput = document.querySelector(`input[name="${dateFieldName}"]`);
  if (!timeInput || !dateInput) {
    return;
  }

  const timeParts = timeInput.value.split(":").map((part) => Number(part));
  if (timeParts.length !== 2 || !Number.isFinite(timeParts[0]) || !Number.isFinite(timeParts[1])) {
    return;
  }

  const hours = timeParts[0];
  const minutes = timeParts[1];
  const totalMinutes = hours * 60 + minutes + deltaMinutes;
  const dayDelta = Math.trunc(totalMinutes / (60 * 24));
  const normalizedTotalMinutes = ((totalMinutes % (60 * 24)) + (60 * 24)) % (60 * 24);
  const adjustedHours = Math.floor(normalizedTotalMinutes / 60);
  const adjustedMinutes = normalizedTotalMinutes % 60;

  timeInput.value = `${padTwo(adjustedHours)}:${padTwo(adjustedMinutes)}`;
  if (dayDelta !== 0) {
    dateInput.value = addDaysToDateString(dateInput.value, dayDelta);
  }
}

function bindTimeStepButtons() {
  const timeStepButtons = document.querySelectorAll(".time-step-button");
  for (const button of timeStepButtons) {
    const timeFieldName = button.dataset.timeInput;
    const dateFieldName = button.dataset.dateInput;
    const deltaMinutes = Number(button.dataset.deltaMinutes || 0);
    if (!timeFieldName || !dateFieldName || !Number.isFinite(deltaMinutes)) {
      continue;
    }

    button.addEventListener("click", (event) => {
      event.preventDefault();
      adjustTimeField(timeFieldName, dateFieldName, deltaMinutes);
    });
  }
}

const reviewRows = document.querySelectorAll(".review-table-row[data-review-url]");
for (const reviewRow of reviewRows) {
  const reviewUrl = reviewRow.getAttribute("data-review-url");
  if (!reviewUrl) {
    continue;
  }

  reviewRow.addEventListener("click", () => {
    window.location.href = reviewUrl;
  });

  reviewRow.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      window.location.href = reviewUrl;
    }
  });
}

bindTimeStepButtons();
