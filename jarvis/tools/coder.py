"""Voice-to-code — Jarvis writes and runs scripts from voice commands."""

import os
import subprocess
import datetime
from pathlib import Path

import anthropic

from jarvis.config import ANTHROPIC_API_KEY
from jarvis.tools.base import Tool, registry

SCRIPTS_DIR = Path.home() / "Desktop" / "jarvis_scripts"
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


def write_code(description: str = "", language: str = "python", run: bool = True, **kwargs) -> str:
    """Generate code from a description, save it, and optionally run it."""
    if not description:
        return "Tell me what you want the script to do."

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": f"""Write a {language} script that does the following:
{description}

Rules:
- Output ONLY the code, no explanations before or after
- Include comments in the code explaining what each part does
- Make it complete and runnable
- If it needs user input, use sensible defaults
- For Python: use only standard library + common packages (requests, etc.)
- Print results to console so the user can see the output"""
            }],
        )

        code = resp.content[0].text

        # Strip markdown code blocks if present
        if "```" in code:
            import re
            match = re.search(r'```(?:\w+)?\n(.*?)```', code, re.DOTALL)
            if match:
                code = match.group(1)

        # Save the script
        ext = {"python": "py", "javascript": "js", "bash": "bat", "powershell": "ps1"}.get(language.lower(), "py")
        timestamp = datetime.datetime.now().strftime("%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in description[:30]).strip().replace(" ", "_")
        filename = f"jarvis_{safe_name}_{timestamp}.{ext}"
        filepath = SCRIPTS_DIR / filename
        filepath.write_text(code, encoding="utf-8")

        result = f"Script saved to {filepath}."

        # Run it if requested
        if run and language.lower() == "python":
            try:
                proc = subprocess.run(
                    ["python", str(filepath)],
                    capture_output=True, text=True, timeout=30,
                    cwd=str(SCRIPTS_DIR),
                )
                output = proc.stdout.strip()
                errors = proc.stderr.strip()

                if proc.returncode == 0:
                    result += f"\n\nOutput:\n{output[:500]}" if output else "\n\nScript ran successfully (no output)."
                else:
                    result += f"\n\nError:\n{errors[:300]}"

                    # Try to fix the error
                    fix_resp = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=500,
                        messages=[{
                            "role": "user",
                            "content": f"This Python script has an error. Fix it. Output ONLY the corrected code:\n\nCode:\n{code}\n\nError:\n{errors}"
                        }],
                    )
                    fixed = fix_resp.content[0].text
                    if "```" in fixed:
                        match = re.search(r'```(?:\w+)?\n(.*?)```', fixed, re.DOTALL)
                        if match:
                            fixed = match.group(1)

                    filepath.write_text(fixed, encoding="utf-8")
                    proc2 = subprocess.run(
                        ["python", str(filepath)],
                        capture_output=True, text=True, timeout=30,
                        cwd=str(SCRIPTS_DIR),
                    )
                    if proc2.returncode == 0:
                        output2 = proc2.stdout.strip()
                        result = f"Fixed and re-ran successfully.\n\nOutput:\n{output2[:500]}" if output2 else "Fixed and ran — no output."

            except subprocess.TimeoutExpired:
                result += "\n\nScript timed out after 30 seconds."
            except Exception as e:
                result += f"\n\nCouldn't run: {e}"

        elif run and language.lower() in ("powershell", "ps1"):
            try:
                proc = subprocess.run(
                    ["powershell", "-File", str(filepath)],
                    capture_output=True, text=True, timeout=30,
                )
                output = proc.stdout.strip()
                result += f"\n\nOutput:\n{output[:500]}" if output else "\n\nScript ran (no output)."
            except Exception as e:
                result += f"\n\nCouldn't run: {e}"

        # Open the file in default editor
        try:
            os.startfile(str(filepath))
        except Exception:
            pass

        return result

    except Exception as e:
        return f"Code generation failed: {e}"


def run_script(path: str = "", **kwargs) -> str:
    """Run an existing script file."""
    if not path:
        # List recent scripts
        scripts = sorted(SCRIPTS_DIR.glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not scripts:
            return "No scripts found. Ask me to write one."
        lines = ["Recent scripts:"]
        for s in scripts[:10]:
            lines.append(f"  {s.name}")
        return "\n".join(lines)

    filepath = Path(path) if os.path.isabs(path) else SCRIPTS_DIR / path

    if not filepath.exists():
        return f"Script not found: {filepath}"

    try:
        ext = filepath.suffix.lower()
        if ext == ".py":
            proc = subprocess.run(["python", str(filepath)], capture_output=True, text=True, timeout=30)
        elif ext in (".ps1",):
            proc = subprocess.run(["powershell", "-File", str(filepath)], capture_output=True, text=True, timeout=30)
        elif ext == ".bat":
            proc = subprocess.run([str(filepath)], capture_output=True, text=True, timeout=30, shell=True)
        else:
            return f"Don't know how to run .{ext} files."

        output = proc.stdout.strip()
        errors = proc.stderr.strip()
        if proc.returncode == 0:
            return f"Output:\n{output[:500]}" if output else "Ran successfully (no output)."
        return f"Error:\n{errors[:300]}"
    except subprocess.TimeoutExpired:
        return "Script timed out after 30 seconds."
    except Exception as e:
        return f"Failed to run: {e}"


# ─── Register ───

def _strip_markdown(code: str) -> str:
    """Aggressively strip markdown code blocks from AI output."""
    import re
    code = code.strip()
    code = re.sub(r'^```(?:html|HTML)?\s*\n?', '', code)
    code = re.sub(r'\n?```\s*$', '', code)
    code = code.strip()
    if not code.startswith('<!') and not code.startswith('<html'):
        idx = code.find('<!DOCTYPE')
        if idx == -1:
            idx = code.find('<html')
        if idx >= 0:
            code = code[idx:]
    return code


# Premium Apple-style design system — injected into every generated site
THEMES = {
    "apple": {
        "name": "Apple Clean",
        "font_import": "Outfit:wght@300;400;500;600;700;800;900",
        "font_family": "'Sora', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        "bg": "#ffffff", "bg_alt": "#f5f5f7", "bg_dark": "#1d1d1f",
        "text": "#1d1d1f", "text_sec": "#6e6e73", "text_light": "#86868b",
        "accent": "#0071e3", "accent_hover": "#0077ed",
        "border": "rgba(0,0,0,0.08)", "navbar_bg": "rgba(255,255,255,0.72)",
        "radius": "20px", "btn_radius": "980px",
    },
    "midnight": {
        "name": "Midnight Dark",
        "font_import": "Sora:wght@300;400;500;600;700;800",
        "font_family": "'Sora', sans-serif",
        "bg": "#0a0a0f", "bg_alt": "#111118", "bg_dark": "#000000",
        "text": "#e8e8ed", "text_sec": "#8b8b99", "text_light": "#5a5a6e",
        "accent": "#6366f1", "accent_hover": "#818cf8",
        "border": "rgba(255,255,255,0.06)", "navbar_bg": "rgba(10,10,15,0.8)",
        "radius": "16px", "btn_radius": "12px",
    },
    "warm": {
        "name": "Warm Minimal",
        "font_import": "Sora:wght@300;400;500;600;700;800",
        "font_family": "'Sora', sans-serif",
        "bg": "#faf8f5", "bg_alt": "#f0ece4", "bg_dark": "#1a1714",
        "text": "#1a1714", "text_sec": "#6b6560", "text_light": "#9a9490",
        "accent": "#c45d3e", "accent_hover": "#d4694a",
        "border": "rgba(0,0,0,0.06)", "navbar_bg": "rgba(250,248,245,0.85)",
        "radius": "12px", "btn_radius": "8px",
    },
    "neon": {
        "name": "Neon Tech",
        "font_import": "Sora:wght@300;400;500;600;700;800",
        "font_family": "'Sora', sans-serif",
        "bg": "#050510", "bg_alt": "#0c0c1d", "bg_dark": "#000005",
        "text": "#e0e0ff", "text_sec": "#8080b0", "text_light": "#5050a0",
        "accent": "#00d4ff", "accent_hover": "#33ddff",
        "border": "rgba(0,212,255,0.1)", "navbar_bg": "rgba(5,5,16,0.85)",
        "radius": "16px", "btn_radius": "980px",
    },
    "earth": {
        "name": "Earth Organic",
        "font_import": "Sora:wght@300;400;500;600;700;800",
        "font_family": "'Sora', sans-serif",
        "bg": "#f7f5f0", "bg_alt": "#eae6dc", "bg_dark": "#2c2a25",
        "text": "#2c2a25", "text_sec": "#6d6a62", "text_light": "#9a9790",
        "accent": "#2d6a4f", "accent_hover": "#38805f",
        "border": "rgba(0,0,0,0.07)", "navbar_bg": "rgba(247,245,240,0.88)",
        "radius": "24px", "btn_radius": "980px",
    },
    "luxury": {
        "name": "Luxury Gold",
        "font_import": "Sora:wght@300;400;500;600;700;800",
        "font_family": "'Sora', sans-serif",
        "bg": "#0c0c0c", "bg_alt": "#141414", "bg_dark": "#000000",
        "text": "#e8e4dc", "text_sec": "#a09888", "text_light": "#706858",
        "accent": "#c9a96e", "accent_hover": "#d4b87a",
        "border": "rgba(201,169,110,0.15)", "navbar_bg": "rgba(12,12,12,0.9)",
        "radius": "4px", "btn_radius": "0px",
    },
}


def _build_css(theme: dict) -> str:
    heading_font = theme.get("heading_font", theme["font_family"])
    is_dark = theme["bg"].startswith("#0") or theme["bg"] == "#000000"
    card_bg = "rgba(255,255,255,0.04)" if is_dark else "#ffffff"
    card_hover_shadow = "0 12px 40px rgba(0,0,0,0.3)" if is_dark else "0 2px 8px rgba(0,0,0,0.04), 0 12px 40px rgba(0,0,0,0.06)"
    footer_bg = theme["bg_alt"]
    white_ref = "#ffffff" if not is_dark else theme["text"]

    return f'''
@import url('https://fonts.googleapis.com/css2?family={theme["font_import"]}&display=swap');

:root {{
  --color-bg: {theme["bg"]};
  --color-bg-alt: {theme["bg_alt"]};
  --color-bg-dark: {theme["bg_dark"]};
  --color-text: {theme["text"]};
  --color-text-secondary: {theme["text_sec"]};
  --color-text-light: {theme["text_light"]};
  --color-accent: {theme["accent"]};
  --color-accent-hover: {theme["accent_hover"]};
  --color-white: {white_ref};
  --color-border: {theme["border"]};
  --font-family: {theme["font_family"]};
  --font-heading: {heading_font};'''


DESIGN_SYSTEM_CSS_BASE = '''
  --section-padding: clamp(60px, 10vw, 120px) clamp(20px, 5vw, 80px);
  --max-width: 1200px;
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: VAR_RADIUS;
  --radius-xl: 28px;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
  --shadow-md: 0 4px 20px rgba(0,0,0,0.08);
  --shadow-lg: 0 12px 40px rgba(0,0,0,0.12);
  --shadow-card: VAR_CARD_SHADOW;
  --transition: 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94);
  --btn-radius: VAR_BTN_RADIUS;
}

*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
html { scroll-behavior: smooth; -webkit-font-smoothing: antialiased; }
body { font-family: var(--font-family); color: var(--color-text); line-height: 1.5; background: var(--color-bg); overflow-x: hidden; }

h1 { font-family: var(--font-heading); font-size: clamp(2.5rem, 6vw, 4.5rem); font-weight: 700; line-height: 1.08; letter-spacing: -0.03em; }
h2 { font-family: var(--font-heading); font-size: clamp(1.8rem, 4vw, 3rem); font-weight: 700; line-height: 1.12; letter-spacing: -0.02em; }
h3 { font-size: clamp(1.2rem, 2.5vw, 1.5rem); font-weight: 600; line-height: 1.2; }
p { font-size: clamp(1rem, 1.1vw, 1.15rem); line-height: 1.65; color: var(--color-text-secondary); }
.overline { font-size: 0.75rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--color-accent); margin-bottom: 12px; }

.container { max-width: var(--max-width); margin: 0 auto; width: 100%; }
section { padding: var(--section-padding); }
.section-alt { background: var(--color-bg-alt); }
.section-dark { background: var(--color-bg-dark); color: var(--color-white); }
.section-dark p { color: var(--color-text-secondary); }
.text-center { text-align: center; }

.navbar {
  position: fixed; top:0; left:0; right:0; z-index:100;
  padding: 16px clamp(20px,5vw,80px);
  display: flex; align-items: center; justify-content: space-between;
  background: VAR_NAVBAR_BG;
  backdrop-filter: saturate(180%) blur(20px); -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 0.5px solid var(--color-border);
  transition: var(--transition);
}
.navbar.scrolled { box-shadow: var(--shadow-sm); }
.nav-logo { font-size: 1.25rem; font-weight: 700; color: var(--color-text); text-decoration: none; font-family: var(--font-heading); }
.nav-links { display: flex; gap: 32px; list-style: none; }
.nav-links a { font-size: 0.875rem; font-weight: 500; color: var(--color-text-secondary); text-decoration: none; transition: color var(--transition); }
.nav-links a:hover { color: var(--color-text); }
.nav-cta { background: var(--color-accent); color: white; padding: 8px 20px; border-radius: var(--btn-radius); font-size: 0.875rem; font-weight: 500; text-decoration: none; transition: background var(--transition); border:none; cursor:pointer; font-family: var(--font-family); }
.nav-cta:hover { background: var(--color-accent-hover); }
.hamburger { display:none; background:none; border:none; cursor:pointer; padding:8px; }
.hamburger span { display:block; width:20px; height:2px; background:var(--color-text); margin:5px 0; transition:var(--transition); border-radius:2px; }

.hero {
  min-height: 100vh; display:flex; align-items:center; justify-content:center; text-align:center;
  padding: 160px clamp(20px,5vw,80px) var(--section-padding);
}
.hero h1 { max-width: 800px; margin: 0 auto 24px; }
.hero p { max-width: 600px; margin: 0 auto 40px; font-size: clamp(1.1rem,1.3vw,1.35rem); }

.btn {
  display:inline-flex; align-items:center; gap:8px; padding:16px 32px;
  border-radius:var(--btn-radius); font-family:var(--font-family); font-size:1rem; font-weight:500;
  text-decoration:none; cursor:pointer; border:none; transition:all var(--transition);
}
.btn-primary { background:var(--color-accent); color:white; }
.btn-primary:hover { background:var(--color-accent-hover); transform:scale(1.02); }
.btn-secondary { background:transparent; color:var(--color-accent); border:1px solid var(--color-border); }
.btn-secondary:hover { background:rgba(0,0,0,0.03); }

.card-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:24px; margin-top:48px; }
.card {
  background:VAR_CARD_BG; border-radius:var(--radius-lg); padding:40px 32px;
  border:1px solid var(--color-border); transition:all var(--transition);
}
.card:hover { transform:translateY(-4px); box-shadow:var(--shadow-card); border-color:transparent; }
.card-icon { font-size:2.5rem; margin-bottom:20px; display:block; }
.card h3 { margin-bottom:12px; }

.stats-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(200px,1fr)); gap:40px; margin-top:48px; }
.stat { text-align:center; }
.stat-number { font-size:clamp(2.5rem,5vw,4rem); font-weight:800; letter-spacing:-0.03em; color:var(--color-text); line-height:1; font-family:var(--font-heading); }
.stat-label { font-size:0.9rem; color:var(--color-text-light); margin-top:8px; }

.img-rounded { border-radius:var(--radius-lg); width:100%; height:auto; object-fit:cover; }
.img-shadow { box-shadow:var(--shadow-lg); }
.two-col { display:grid; grid-template-columns:1fr 1fr; gap:clamp(40px,6vw,80px); align-items:center; }

.testimonial { max-width:700px; margin:48px auto 0; text-align:center; }
.testimonial blockquote { font-size:clamp(1.15rem,1.4vw,1.4rem); font-style:italic; line-height:1.6; color:var(--color-text); margin-bottom:24px; font-family:var(--font-heading); }
.testimonial cite { font-size:0.9rem; color:var(--color-text-light); font-style:normal; }

.footer { padding:60px clamp(20px,5vw,80px) 30px; background:var(--color-bg-alt); border-top:1px solid var(--color-border); }
.footer-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:40px; max-width:var(--max-width); margin:0 auto 40px; }
.footer-col h4 { font-size:0.75rem; font-weight:600; letter-spacing:0.08em; text-transform:uppercase; color:var(--color-text-light); margin-bottom:16px; }
.footer-col a { display:block; font-size:0.875rem; color:var(--color-text-secondary); text-decoration:none; margin-bottom:10px; transition:color var(--transition); }
.footer-col a:hover { color:var(--color-text); }
.footer-bottom { text-align:center; padding-top:30px; border-top:1px solid var(--color-border); font-size:0.8rem; color:var(--color-text-light); max-width:var(--max-width); margin:0 auto; }

.reveal { opacity:0; transform:translateY(30px); transition:opacity 0.8s ease, transform 0.8s ease; }
.reveal.visible { opacity:1; transform:translateY(0); }

@media(max-width:768px) {
  .nav-links { display:none; }
  .hamburger { display:block; }
  .nav-links.open { display:flex; flex-direction:column; position:absolute; top:100%; left:0; right:0; background:VAR_NAVBAR_BG; backdrop-filter:blur(20px); padding:20px; gap:16px; border-bottom:1px solid var(--color-border); }
  .two-col { grid-template-columns:1fr; }
  .card-grid { grid-template-columns:1fr; }
  .hero { min-height:auto; padding-top:140px; padding-bottom:80px; }
}
'''

DESIGN_SYSTEM_JS = '''
// Scroll reveal
const reveals = document.querySelectorAll('.reveal');
const observer = new IntersectionObserver((entries) => {
  entries.forEach(e => { if(e.isIntersecting) { e.target.classList.add('visible'); observer.unobserve(e.target); } });
}, { threshold: 0.15, rootMargin: '0px 0px -50px 0px' });
reveals.forEach(el => observer.observe(el));

// Navbar scroll effect
const navbar = document.querySelector('.navbar');
if(navbar) {
  window.addEventListener('scroll', () => { navbar.classList.toggle('scrolled', window.scrollY > 40); });
}

// Hamburger toggle
const hamburger = document.querySelector('.hamburger');
const navLinks = document.querySelector('.nav-links');
if(hamburger && navLinks) {
  hamburger.addEventListener('click', () => navLinks.classList.toggle('open'));
  navLinks.querySelectorAll('a').forEach(a => a.addEventListener('click', () => navLinks.classList.remove('open')));
}

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener('click', e => { e.preventDefault(); const t = document.querySelector(a.getAttribute('href')); if(t) t.scrollIntoView({behavior:'smooth'}); });
});
'''


def build_website(description: str = "", theme: str = "", **kwargs) -> str:
    """Two-pass premium website builder with random theme selection."""
    import random

    if not description:
        return "Tell me what kind of website you want."

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Pick a theme — user can specify or let AI choose
        if theme and theme.lower() in THEMES:
            chosen = THEMES[theme.lower()]
        else:
            # Let the AI pick the best theme for the project, or randomize
            theme_options = list(THEMES.keys())
            # Weight selection based on description keywords
            desc_lower = description.lower()
            if any(w in desc_lower for w in ["dark", "tech", "gaming", "cyber"]):
                chosen = THEMES[random.choice(["midnight", "neon"])]
            elif any(w in desc_lower for w in ["luxury", "premium", "gold", "fashion", "jewelry"]):
                chosen = THEMES["luxury"]
            elif any(w in desc_lower for w in ["organic", "natural", "eco", "green", "food"]):
                chosen = THEMES["earth"]
            elif any(w in desc_lower for w in ["warm", "cozy", "cafe", "vintage", "artisan"]):
                chosen = THEMES["warm"]
            elif any(w in desc_lower for w in ["clean", "minimal", "professional", "corporate"]):
                chosen = THEMES["apple"]
            else:
                chosen = THEMES[random.choice(theme_options)]

        # Build the CSS from theme
        is_dark = chosen["bg"].startswith("#0") or chosen["bg"] == "#000000"
        card_bg = "rgba(255,255,255,0.04)" if is_dark else "#ffffff"
        card_shadow = "0 12px 40px rgba(0,0,0,0.3)" if is_dark else "0 2px 8px rgba(0,0,0,0.04), 0 12px 40px rgba(0,0,0,0.06)"

        theme_css = _build_css(chosen)
        full_css = theme_css + DESIGN_SYSTEM_CSS_BASE
        full_css = full_css.replace("VAR_RADIUS", chosen["radius"])
        full_css = full_css.replace("VAR_BTN_RADIUS", chosen["btn_radius"])
        full_css = full_css.replace("VAR_NAVBAR_BG", chosen["navbar_bg"])
        full_css = full_css.replace("VAR_CARD_BG", card_bg)
        full_css = full_css.replace("VAR_CARD_SHADOW", card_shadow)

        theme_hint = f"This is a {chosen['name']} themed site. "
        if is_dark:
            theme_hint += "It uses a DARK background — make text and content bright. "
        else:
            theme_hint += "It uses a LIGHT background. "

        # PASS 1: Generate HTML content using the design system classes
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            messages=[{
                "role": "user",
                "content": f"""Generate the HTML body content for a premium website. I will wrap it in a design system.

PROJECT: {description}
THEME: {theme_hint}

You have these CSS classes available — USE THEM:

LAYOUT: .container, .text-center, .section-alt (alt bg), .section-dark (dark bg)
TEXT: .overline (small uppercase label), h1/h2/h3 (auto-styled), p (auto-styled)
BUTTONS: .btn .btn-primary (accent color), .btn .btn-secondary (outline)
CARDS: .card-grid (auto grid), .card (styled card w/ hover), .card-icon (emoji), h3, p inside card
STATS: .stats-grid (auto grid), .stat > .stat-number + .stat-label
IMAGES: .img-rounded .img-shadow, use https://picsum.photos/WIDTH/HEIGHT for images (vary the numbers)
LAYOUT: .two-col (2 column grid with alignment)
TESTIMONIAL: .testimonial > blockquote + cite
FOOTER: .footer > .footer-grid > .footer-col (h4 + links), .footer-bottom
ANIMATION: add class="reveal" to any element to fade-in on scroll

STRUCTURE REQUIRED:
1. <nav class="navbar"> with .nav-logo (text), ul.nav-links with <a href="#section">links, .nav-cta button, button.hamburger with 3 <span>
2. <section class="hero"> with .container, h1, p, .btn
3. 4-6 more <section> tags using the classes above. Alternate with .section-alt class.
4. Add class="reveal" to cards, stats, images, testimonials for scroll animation
5. <footer class="footer"> with .footer-grid and .footer-bottom

Be CREATIVE with the content — write compelling headlines, real-sounding copy, varied sections. Don't be generic.

OUTPUT ONLY the HTML from <nav> to </footer>. No <!DOCTYPE>, no <html>, no <head>, no <style>, no <script>. Just the body content. No markdown. No code blocks. Start directly with <nav"""
            }],
        )

        body_html = _strip_markdown(resp.content[0].text)

        # Clean up — make sure it starts with <nav
        if not body_html.startswith('<nav') and not body_html.startswith('<'):
            idx = body_html.find('<nav')
            if idx >= 0:
                body_html = body_html[idx:]

        # PASS 2: Assemble full page with design system
        safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in description[:40]).strip().replace(" ", "_")

        full_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{description[:60]}</title>
    <style>{full_css}</style>
</head>
<body>
{body_html}
<script>{DESIGN_SYSTEM_JS}</script>
</body>
</html>'''

        # Save
        timestamp = datetime.datetime.now().strftime("%H%M%S")
        filename = f"jarvis_{safe_name}_{timestamp}.html"
        filepath = SCRIPTS_DIR / filename
        filepath.write_text(full_html, encoding="utf-8")

        os.startfile(str(filepath))
        return f"Website built and opened in your browser. Saved to {filepath}."
    except Exception as e:
        return f"Failed to build website: {e}"


registry.register(Tool(
    name="write_code",
    description="Generate and run code from a description. Use for 'write me a script that...', 'code me a...', 'make a program that...', 'write Python that...'. Auto-saves to Desktop/jarvis_scripts/ and runs it.",
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "What the script should do"},
            "language": {"type": "string", "description": "Programming language: python (default), powershell, javascript"},
            "run": {"type": "boolean", "description": "Whether to run the script after creating it (default true)"},
        },
        "required": ["description"],
    },
    handler=write_code,
))

registry.register(Tool(
    name="build_website",
    description="Build a premium website from a description. Each site gets a unique design theme (apple, midnight, warm, neon, earth, luxury) auto-selected based on the project. Use for 'build me a website', 'make me a landing page', 'create a portfolio site'.",
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "What the website should be — describe layout, features, content, style"},
            "theme": {"type": "string", "description": "Optional design theme: apple (clean white), midnight (dark purple), warm (earthy tones), neon (dark cyan), earth (green organic), luxury (black gold). Auto-picked if omitted."},
        },
        "required": ["description"],
    },
    handler=build_website,
))

registry.register(Tool(
    name="run_script",
    description="Run an existing script or list recent scripts. Use for 'run that script', 'list my scripts', 'execute the last script'.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Script filename or path (empty to list recent scripts)"},
        },
    },
    handler=run_script,
))
