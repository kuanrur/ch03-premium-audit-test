"""Parse the company's classification guide (Markdown) into citable paragraphs.

Each paragraph starts with a bold identifier, for example

    **CG-11. R-310 Roofing.** Installation, repair and removal of roofs ...

General paragraphs have no class code; class-code paragraphs start their title with
the code. A class code is cited by the identifier of the paragraph that describes it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PARA_RE = re.compile(r"^\*\*(?P<id>CG-\d+)\.\s+(?P<title>.+?)\*\*\s*(?P<text>.*)$", re.S)
CODE_RE = re.compile(r"^(?P<code>[A-Z]-\d{3})\s+(?P<name>.+)$")


class GuideError(ValueError):
    pass


@dataclass
class Paragraph:
    id: str
    title: str
    text: str
    code: str | None = None
    code_name: str | None = None


@dataclass
class Guide:
    path: Path
    edition: str
    paragraphs: dict[str, Paragraph]

    def code_paragraph(self, code: str) -> Paragraph:
        for p in self.paragraphs.values():
            if p.code == code:
                return p
        raise GuideError(f"class code {code} is not described in {self.path.name}")

    def has_code(self, code: str) -> bool:
        return any(p.code == code for p in self.paragraphs.values())

    @property
    def codes(self) -> list[str]:
        return [p.code for p in self.paragraphs.values() if p.code]

    def office_code(self) -> str:
        """The clerical code: the code paragraph that limits duties to an office."""
        hits = [p.code for p in self.paragraphs.values() if p.code and "confined to an office" in p.text]
        if len(hits) != 1:
            raise GuideError("could not identify the single clerical office code in the guide")
        return hits[0]

    def require(self, para_id: str) -> Paragraph:
        if para_id not in self.paragraphs:
            raise GuideError(f"the guide has no paragraph {para_id}; the rules this Skill applies depend on it")
        return self.paragraphs[para_id]


def load_guide(path: Path) -> Guide:
    text = path.read_text(encoding="utf-8")
    edition_m = re.search(r"Edition of ([A-Za-z]+ \d{4})", text)
    paragraphs: dict[str, Paragraph] = {}
    for block in re.split(r"\n\s*\n", text):
        block = " ".join(line.strip() for line in block.strip().splitlines())
        m = PARA_RE.match(block)
        if not m:
            continue
        title = m.group("title").strip().rstrip(".")
        para = Paragraph(id=m.group("id"), title=title, text=m.group("text").strip())
        cm = CODE_RE.match(title)
        if cm:
            para.code, para.code_name = cm.group("code"), cm.group("name")
        if para.id in paragraphs:
            raise GuideError(f"paragraph {para.id} appears twice in {path.name}")
        paragraphs[para.id] = para
    if not paragraphs:
        raise GuideError(f"no CG-nn paragraphs found in {path}")
    return Guide(path=path, edition=edition_m.group(1) if edition_m else "unknown", paragraphs=paragraphs)
