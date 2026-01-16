document.addEventListener("input", (e) => {
  const col = e.target.closest(".column[data-edited]");
  if (col) col.dataset.edited = "true";
});

