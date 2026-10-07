"""Check only local compiled assets; never resolve network resources or infer research."""

from html.parser import HTMLParser
from pathlib import Path


class AssetReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"src", "href"} and value and value.startswith("/assets/"):
                self.references.append(value)


def frontend_available(directory: Path) -> bool:
    try:
        parser = AssetReferences()
        parser.feed((directory / "index.html").read_text(encoding="utf-8"))
        assets = (directory / "assets").resolve()
        return bool(parser.references) and all(
            (directory / reference.lstrip("/")).resolve().is_relative_to(assets)
            and (directory / reference.lstrip("/")).is_file()
            for reference in parser.references
        )
    except (OSError, UnicodeError, ValueError):
        return False
