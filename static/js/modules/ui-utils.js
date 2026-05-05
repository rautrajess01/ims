(function () {
  function setLoadingRows(tbody, colSpan, rows) {
    rows = rows || 2;
    if (!tbody) return;
    var html = "";
    for (var i = 0; i < rows; i += 1) {
      html += '<tr><td colspan="' + colSpan + '" class="p-3"><div class="ims-loading" style="height:18px"></div></td></tr>';
    }
    tbody.innerHTML = html;
  }

  function setEmptyRow(tbody, colSpan, message, className) {
    if (!tbody) return;
    tbody.innerHTML =
      '<tr><td colspan="' +
      colSpan +
      '" class="text-center p-4 ' +
      (className || "text-secondary") +
      '">' +
      message +
      "</td></tr>";
  }

  window.imsUi = {
    setLoadingRows: setLoadingRows,
    setEmptyRow: setEmptyRow,
  };
})();
