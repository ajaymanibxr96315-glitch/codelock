from pathlib import Path
import re

report = Path(__file__).resolve().parent
html = (report / "CodeLock_Project_Report.html").read_text(encoding="utf-8")
inject = """
<script>
window.addEventListener('load', function () {
  var rows = [];
  document.querySelectorAll('.page').forEach(function (p, i) {
    rows.push('PAGE ' + (i + 1) + ' scroll=' + p.scrollHeight + ' client=' + p.clientHeight + ' overflow=' + (p.scrollHeight - p.clientHeight));
  });
  var pre = document.createElement('pre');
  pre.id = 'overflow-report';
  pre.textContent = rows.join(' ; ');
  document.body.appendChild(pre);
});
</script>
"""
html = html.replace("</body>", inject + "</body>")
(report / "_preview" / "measure.html").write_text(html.replace('src="assets/', 'src="../assets/'), encoding="utf-8")
print("wrote measure.html")
