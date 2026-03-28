"""Image generation tools — AI image creation via Pollinations.ai (Flux model)."""

import os
import datetime
import urllib.parse
from pathlib import Path

import httpx

from jarvis.tools.base import Tool, registry

DESKTOP = Path.home() / "Desktop"
IMAGES_DIR = DESKTOP / "jarvis_images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

POLLINATIONS_KEY = os.getenv("POLLINATIONS_API_KEY", "")


def generate_image(prompt: str = "", style: str = "", **kwargs) -> str:
    """Generate an image from a text prompt using Pollinations Flux model."""
    if not prompt:
        return "I need a description of what to generate."

    full_prompt = prompt
    if style:
        full_prompt = f"{style} style, {prompt}"

    encoded = urllib.parse.quote(full_prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?key={POLLINATIONS_KEY}&model=flux&width=1024&height=1024&nologo=true"

    try:
        resp = httpx.get(url, timeout=90, follow_redirects=True)
        if resp.status_code != 200 or len(resp.content) < 5000:
            return f"Image generation failed (status {resp.status_code})."

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in prompt[:40]).strip().replace(" ", "_")
        filepath = IMAGES_DIR / f"jarvis_{safe_name}_{timestamp}.jpg"
        filepath.write_bytes(resp.content)
        os.startfile(str(filepath))

        return f"Image generated and saved. Opening it now."
    except httpx.TimeoutException:
        return "Image generation timed out. Try a simpler prompt."
    except Exception as e:
        return f"Error generating image: {e}"


registry.register(Tool(
    name="generate_image",
    description="Generate an AI image from a text description. Use for 'draw me', 'create an image of', 'generate a picture of' requests.",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed description of the image to generate",
            },
            "style": {
                "type": "string",
                "description": "Optional art style (e.g. 'photorealistic', 'anime', 'oil painting', 'pixel art')",
            },
        },
        "required": ["prompt"],
    },
    handler=generate_image,
))
