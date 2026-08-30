// Consolidated operator hotkey manager. Loaded last, after renderer.js and
// panels.js, and reuses their globals (advanceVerse, retreatVerse,
// referenceInput, keywordInput, clearBtn, pendingLog, favoriteCurrent,
// queueCurrent, advanceQueue).
//
// Two listeners, matching the two cases that existed before this file:
// - Bubble phase (default) for everything that should NOT fire while a text
//   field has focus — arrow keys and the new letter hotkeys. Input fields
//   already stop propagation on their own keydown (see wireSearchField in
//   renderer.js), so nothing here needs to duplicate that guard beyond the
//   tag-name check below (defense in depth for any future input that
//   doesn't call stopPropagation).
// - Capture phase for F5/F6, so they win focus away from a field even while
//   that field already has focus (the one case that *needs* to override
//   in-progress typing).

function isTypingTarget(target) {
  if (target === deviceSelect) return true; // preserve native <select> arrow-key behavior
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

document.addEventListener("keydown", (event) => {
  // Checked against both event.target and document.activeElement (normally
  // identical for a real keydown, but not guaranteed to be — e.g. a focus
  // change mid-dispatch, or any retargeting) as a second, independent guard
  // against the arrow keys ever reaching a search field's own text-cursor
  // navigation and driving the app's verse navigation at the same time.
  if (isTypingTarget(event.target) || isTypingTarget(document.activeElement)) return;
  if (themeModal && !themeModal.hidden) return; // theme.js's own Escape handler owns the modal

  switch (event.key) {
    case "ArrowDown":
    case "ArrowRight":
      event.preventDefault();
      advanceVerse();
      break;
    case "ArrowUp":
    case "ArrowLeft":
      event.preventDefault();
      retreatVerse();
      break;
    case "c":
    case "C":
      if (!clearBtn.disabled) clearBtn.click();
      break;
    case "a":
    case "A": {
      const topPending = pendingLog.firstElementChild;
      const approveBtn = topPending && topPending.querySelector(".approve-btn");
      if (approveBtn) approveBtn.click();
      break;
    }
    case "d":
    case "D": {
      const topPending = pendingLog.firstElementChild;
      const dismissBtn = topPending && topPending.querySelector(".dismiss-btn");
      if (dismissBtn) dismissBtn.click();
      break;
    }
    case "f":
    case "F":
      favoriteCurrent();
      break;
    case "q":
    case "Q":
      queueCurrent();
      break;
    case "n":
    case "N":
      advanceQueue();
      break;
    default:
      break;
  }
});

// F5 -> focus + highlight the reference field, F6 -> keyword field. Registered
// on the capture phase so they win even if a field already has focus.
document.addEventListener(
  "keydown",
  (event) => {
    if (event.key === "F5") {
      event.preventDefault();
      referenceInput.focus();
      referenceInput.select();
    } else if (event.key === "F6") {
      event.preventDefault();
      keywordInput.focus();
      keywordInput.select();
    }
  },
  true
);
