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
