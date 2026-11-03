"""What an appeal needs on file, by denial type, and which of it the user already uploaded."""

from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import DenialCategory, DocumentCheck


@dataclass
class UploadedDoc:
    name: str
    kind: str  # "denial" | "policy" | "supporting"
    text: str
    data: bytes = field(default=b"", repr=False)


# requirement -> keywords that show it is present (in the filename or the text)
BASE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "Denial / repudiation letter": ("repudiat", "rejection", "denial", "not admissible"),
    "Policy wording or schedule": ("policy wording", "policy schedule", "terms and conditions"),
    "Discharge summary": ("discharge summary", "discharge"),
    "Itemised final hospital bill": ("final bill", "itemised", "itemized", "invoice", "bill"),
    "Payment receipts": ("receipt", "paid"),
    "Investigation / lab reports": ("report", "investigation", "lab", "radiology", "mri", "x-ray"),
}

CATEGORY_REQUIREMENTS: dict[DenialCategory, dict[str, tuple[str, ...]]] = {
    DenialCategory.PRE_EXISTING: {
        "Treating doctor's certificate on date of first diagnosis": (
            "first diagnos",
            "certificate",
        ),
        "Past medical records / prescriptions": ("prescription", "past", "history"),
    },
    DenialCategory.WAITING_PERIOD: {
        "Previous policy copies / portability continuity proof": (
            "portability",
            "previous policy",
            "renewal",
            "continuity",
        ),
    },
    DenialCategory.NOT_MEDICALLY_NECESSARY: {
        "Letter of medical necessity from the treating doctor": ("medical necessity", "necessity"),
    },
    DenialCategory.ROOM_RENT_LIMIT: {
        "Hospital room-category tariff": ("tariff", "room category"),
    },
    DenialCategory.LATE_INTIMATION: {
        "Letter explaining the reason for late intimation": ("delay", "late intimation"),
    },
    DenialCategory.NON_DISCLOSURE: {
        "Proposal form copy": ("proposal form",),
        "Doctor's letter on when the condition began": ("onset", "first diagnos"),
    },
    DenialCategory.DAYCARE_OPD: {
        "Doctor's note on why hospitalisation / daycare was needed": ("daycare", "admission"),
    },
}


def check_documents(category: DenialCategory, docs: list[UploadedDoc]) -> DocumentCheck:
    requirements = dict(BASE_REQUIREMENTS)
    requirements.update(CATEGORY_REQUIREMENTS.get(category, {}))
    haystacks = [f"{d.name}\n{d.text[:5000]}".lower() for d in docs]
    kinds = {d.kind for d in docs}

    present, missing = [], []
    for req, keywords in requirements.items():
        uploaded_as_kind = (req.startswith("Denial") and "denial" in kinds) or (
            req.startswith("Policy") and "policy" in kinds
        )
        if uploaded_as_kind or any(k in h for h in haystacks for k in keywords):
            present.append(req)
        else:
            missing.append(req)

    notes = []
    if missing:
        notes.append(
            "Attach the missing items to the appeal; insurers often reject incomplete files."
        )
    return DocumentCheck(present=present, missing=missing, notes=notes)
