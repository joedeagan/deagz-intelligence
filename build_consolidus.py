"""One-off script to build the Consolidus redesign."""
import anthropic, os, re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(str(Path(__file__).parent / ".env"), override=True)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

prompt = """You are an elite frontend designer. Redesign the Consolidus website as a stunning single-file HTML page.

ABOUT CONSOLIDUS:
- B2B branded merchandise company. Tagline: Branded Merchandise, Simplified
- Serves: Higher Education, Government, Non-Profits, Other Organizations
- Key stats: 31% avg cost savings, 400+ vetted suppliers, 7x Inc 5000 honoree
- Colors: Primary navy blue #16469D, clean whites, professional

SECTIONS:
1. Sticky navbar with logo text and smooth scroll nav + Get Started CTA button
2. Hero - large headline "Branded Merchandise, Simplified" with gradient bg and CTA
3. Client logos - "Trusted by leading institutions" with text logos in a row
4. Who We Serve - 4 glass cards (Higher Ed, Government, Non-Profit, Other Orgs)
5. Why Consolidus - 6 feature boxes with emoji icons
6. Numbers That Matter - big stats (31%, 400+, 50%+, 7x Inc 5000)
7. Testimonial quote
8. CTA - "Ready to simplify branded merchandise?"
9. Footer with link columns

DESIGN:
- Google Fonts (Inter + Space Grotesk)
- Navy #16469D primary with modern gradients
- Glass morphism cards (backdrop-filter blur, semi-transparent)
- Scroll fade-in animations via Intersection Observer
- Hover effects on cards and buttons (scale, shadow lift)
- Large bold typography (60px hero)
- Generous whitespace and padding
- Mobile responsive with hamburger menu
- Sticky navbar that darkens on scroll
- CSS custom properties for all colors
- Professional Apple/Stripe quality

CRITICAL: Output ONLY the raw HTML. No markdown. No code blocks. No backticks. No explanations. Start with <!DOCTYPE html> and end with </html>."""

resp = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=16000,
    messages=[{"role": "user", "content": prompt}],
)

code = resp.content[0].text.strip()

# Aggressively strip markdown
code = re.sub(r"^```\w*\s*\n?", "", code)
code = re.sub(r"\n?```\s*$", "", code)

# Find HTML start
if not code.startswith("<!"):
    idx = code.find("<!DOCTYPE")
    if idx == -1:
        idx = code.find("<html")
    if idx >= 0:
        code = code[idx:]

filepath = Path.home() / "Desktop" / "jarvis_scripts" / "consolidus_redesign.html"
filepath.parent.mkdir(exist_ok=True)
filepath.write_text(code, encoding="utf-8")

print(f"Saved: {len(code)} chars")
print(f"Starts: {code[:40]}")
print(f"Complete: {code.rstrip().endswith('</html>')}")

os.startfile(str(filepath))
print("Opened in browser!")
