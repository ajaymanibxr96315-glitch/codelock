from pathlib import Path
import re
import subprocess
import sys

report = Path(__file__).resolve().parent
out = report / "_preview"
out.mkdir(exist_ok=True)
html = (report / "CodeLock_Project_Report.html").read_text(encoding="utf-8")
head = html.split("<body>")[0] + "<body>"
sections = re.findall(r'<section class="page.*?</section>', html, re.S)
print("sections", len(sections))
chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
for i, sec in enumerate(sections, 1):
    p = out / f"page-{i:02d}.html"
    p.write_text((head + sec + "</body></html>").replace('src="assets/', 'src="../assets/'), encoding="utf-8")
    png = out / f"page-{i:02d}.png"
    subprocess.run([
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--window-size=794,1122",
        f"--screenshot={png}", p.as_uri(),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    print("rendered", png.name)
