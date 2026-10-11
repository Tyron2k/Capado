"""Tiny real raster files and a harmless active SVG for logo regressions."""

import base64

RASTER_LOGOS = {
    "image/png": base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgaHAAAAFEAMERbpc7AAAAAElFTkSuQmCC"
    ),
    "image/jpeg": base64.b64decode(
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDkaKKK5j4s/9k="
    ),
    "image/webp": base64.b64decode(
        "UklGRjgAAABXRUJQVlA4ICwAAABwAQCdASoBAAEAAUAmJaACdAIHgAD+8U2tcXNkRR/9ZX//zK//+ZX+7sAAAA=="
    ),
    "image/gif": base64.b64decode(
        "R0lGODdhAQABAIEAAACAQAAAAAAAAAAAACwAAAAAAQABAAAIBAABBAQAOw=="
    ),
}

ACTIVE_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36"
onload="document.documentElement.setAttribute('data-onload', 'executed')">
<rect width="36" height="36" fill="green"/>
<script>document.documentElement.setAttribute('data-script', 'executed')</script>
<image href="/logo-security-external-probe"/>
</svg>"""
