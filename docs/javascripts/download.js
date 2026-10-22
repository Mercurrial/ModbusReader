// The download button on the home page follows the visitor's system.
//
// The page ships the Windows link (it works without JavaScript); the button
// carries the other variants in data-* attributes:
//   data-linux-href / data-linux-label, data-mac-href / data-mac-label,
//   data-mobile-href / data-mobile-label (a phone cannot run the app — the
//   button leads to the install page instead).
(function () {
  function system() {
    var ua = navigator.userAgent || "";
    var platform = (navigator.userAgentData && navigator.userAgentData.platform) ||
                   navigator.platform || "";
    if (/Android|iPhone|iPad|iPod/i.test(ua) ||
        (/Mac/i.test(platform) && navigator.maxTouchPoints > 1)) return "mobile";
    if (/Win/i.test(platform) || /Windows/i.test(ua)) return "windows";
    if (/Mac/i.test(platform) || /Mac OS X/i.test(ua)) return "mac";
    if (/Linux|X11|CrOS/i.test(platform) || /Linux/i.test(ua)) return "linux";
    return "windows";
  }

  function apply() {
    var button = document.getElementById("mr-download");
    if (!button) return;
    var os = system();
    var href = button.getAttribute("data-" + os + "-href");
    var label = button.getAttribute("data-" + os + "-label");
    if (href) button.setAttribute("href", href);
    if (label) {
      // Keep the icon (the first child span), replace only the text.
      var text = Array.prototype.find.call(button.childNodes, function (n) {
        return n.nodeType === 3 && n.textContent.trim();
      });
      if (text) text.textContent = " " + label;
    }
    button.setAttribute("data-os", os);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", apply);
  } else {
    apply();
  }
})();
