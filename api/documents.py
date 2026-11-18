"""PDF documents: a member's proof of registration, and the admin record.

Both were drawn with absolute canvas coordinates - every line placed by hand
at a fixed y, nothing wrapping, nothing centred, and a long department or
village simply running off the edge of the page. They are built with Platypus
here instead, so the flowables lay themselves out, text wraps, and adding a
field does not mean renumbering everything below it.

Two documents, deliberately different:

* proof_of_registration_pdf - what the member receives. A certificate: who
  they are, that they are registered, and a reference to quote. It states
  what it is for and carries no more personal data than it needs.

* member_record_pdf - what the committee reads in the dashboard. The complete
  record, grouped into sections, including everything the member submitted.
"""

import os
from io import BytesIO

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Red Cross red, and the greys used for rules and secondary text.
RED = colors.HexColor("#ED1B2E")
INK = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#6B7280")
RULE = colors.HexColor("#E5E7EB")
BAND = colors.HexColor("#F9FAFB")

ORGANISATION = "Rwanda Red Cross"
COMMITTEE = "Nyarugenge Committee"

PAGE_MARGIN = 18 * mm


def _styles():
    s = getSampleStyleSheet()
    return {
        "org": ParagraphStyle(
            "org", parent=s["Normal"], fontName="Helvetica-Bold",
            fontSize=15, textColor=RED, leading=18,
        ),
        "sub": ParagraphStyle(
            "sub", parent=s["Normal"], fontName="Helvetica",
            fontSize=9.5, textColor=MUTED, leading=12,
        ),
        "title": ParagraphStyle(
            "title", parent=s["Normal"], fontName="Helvetica-Bold",
            fontSize=19, textColor=INK, leading=23, alignment=TA_CENTER,
            spaceBefore=6, spaceAfter=2,
        ),
        "kicker": ParagraphStyle(
            "kicker", parent=s["Normal"], fontName="Helvetica",
            fontSize=9.5, textColor=MUTED, leading=12, alignment=TA_CENTER,
        ),
        "body": ParagraphStyle(
            "body", parent=s["Normal"], fontName="Helvetica",
            fontSize=10.5, textColor=INK, leading=16,
        ),
        "section": ParagraphStyle(
            "section", parent=s["Normal"], fontName="Helvetica-Bold",
            fontSize=10, textColor=RED, leading=13, spaceBefore=4, spaceAfter=4,
        ),
        "label": ParagraphStyle(
            "label", parent=s["Normal"], fontName="Helvetica",
            fontSize=9.5, textColor=MUTED, leading=13,
        ),
        "value": ParagraphStyle(
            "value", parent=s["Normal"], fontName="Helvetica-Bold",
            fontSize=10, textColor=INK, leading=13,
        ),
    }


# The source logo is ~3700x4000px and 887KB. Embedded as-is it made every
# one-page PDF 900KB, almost all of it a mark printed 16mm tall. It is
# downscaled once per process and the small version reused.
_LOGO_CACHE = {}
_LOGO_MAX_PX = 260


def _logo_bytes():
    """A small PNG of the logo, or None if it cannot be read."""
    if "data" in _LOGO_CACHE:
        return _LOGO_CACHE["data"]

    _LOGO_CACHE["data"] = None
    for path in (
        os.path.join(settings.STATIC_ROOT, "logo.png"),
        os.path.join(settings.BASE_DIR, "static", "logo.png"),
    ):
        if not os.path.exists(path):
            continue
        try:
            from PIL import Image as PILImage

            with PILImage.open(path) as im:
                im = im.convert("RGBA")
                im.thumbnail((_LOGO_MAX_PX, _LOGO_MAX_PX))
                out = BytesIO()
                im.save(out, format="PNG", optimize=True)
            _LOGO_CACHE["data"] = out.getvalue()
            _LOGO_CACHE["size"] = im.size
        except Exception:
            # A missing or unreadable logo must not stop a member getting
            # their certificate; the document simply prints without the mark.
            _LOGO_CACHE["data"] = None
        break
    return _LOGO_CACHE["data"]


def _logo(height=16 * mm):
    """The committee logo, scaled to a height and kept in proportion."""
    data = _logo_bytes()
    if not data:
        return None
    try:
        width_px, height_px = _LOGO_CACHE.get("size", (1, 1))
        ratio = width_px / float(height_px or 1)
        img = Image(BytesIO(data))
        img.drawHeight = height
        img.drawWidth = height * ratio
        return img
    except Exception:
        return None


def _letterhead(styles):
    """Logo on the left, organisation on the right, over a red rule."""
    mark = _logo()
    text = [
        Paragraph(ORGANISATION, styles["org"]),
        Paragraph(COMMITTEE, styles["sub"]),
    ]
    row = [[mark or "", text]]
    table = Table(row, colWidths=[22 * mm, None])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -1), 1.4, RED),
            ]
        )
    )
    return table


def _field_table(styles, rows, label_width=45 * mm):
    """A two-column label/value block.

    Paragraph in both cells so a long village name or department wraps instead
    of running past the margin, which is what the old fixed drawString did.
    """
    data = [
        [Paragraph(str(label), styles["label"]), Paragraph(str(value if value not in (None, "") else "—"), styles["value"])]
        for label, value in rows
    ]
    table = Table(data, colWidths=[label_width, None], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
            ]
        )
    )
    return table


def _section(styles, heading, rows):
    """A headed block that will not be split across a page break."""
    return KeepTogether(
        [Paragraph(heading.upper(), styles["section"]), _field_table(styles, rows), Spacer(1, 7 * mm)]
    )


def _footer(canvas, doc, note):
    """Page furniture: a rule, the note, and 'Page n of m' on every page."""
    canvas.saveState()
    width, _ = A4
    y = 13 * mm
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(PAGE_MARGIN, y + 6 * mm, width - PAGE_MARGIN, y + 6 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(PAGE_MARGIN, y, note)
    canvas.drawRightString(width - PAGE_MARGIN, y, "Page %d" % canvas.getPageNumber())
    canvas.restoreState()


def _build(story, title, note):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=16 * mm,
        bottomMargin=24 * mm,
        title=title,
        author=ORGANISATION,
    )
    draw = lambda c, d: _footer(c, d, note)  # noqa: E731
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    buffer.seek(0)
    return buffer


# --------------------------------------------------------------------------- #
# Helpers over the record
# --------------------------------------------------------------------------- #


def _full_name(user):
    name = ("%s %s" % (user.first_name or "", user.last_name or "")).strip()
    return name or user.username


def _address_line(address):
    if not address:
        return "—"
    parts = [address.village, address.cell, address.sector, address.district, address.province]
    return ", ".join(p for p in parts if p)


def reference_for(info):
    """A stable reference the member can quote: RRC-NYA-0007."""
    return "RRC-NYA-%04d" % info.id


def _issued(info):
    from django.utils import timezone

    return timezone.localtime().strftime("%d %B %Y at %H:%M")


# --------------------------------------------------------------------------- #
# The member's certificate
# --------------------------------------------------------------------------- #


def proof_of_registration_pdf(info):
    """What the member downloads after submitting their information."""
    styles = _styles()
    user = info.user
    name = _full_name(user)
    ref = reference_for(info)

    story = [
        _letterhead(styles),
        Spacer(1, 10 * mm),
        Paragraph("Proof of Registration", styles["title"]),
        Paragraph("Reference %s" % ref, styles["kicker"]),
        Spacer(1, 9 * mm),
        Paragraph(
            "This is to certify that <b>%s</b> is registered as a member of the "
            "%s, %s. The details below are as submitted by the member and held "
            "on the committee's register." % (name, ORGANISATION, COMMITTEE),
            styles["body"],
        ),
        Spacer(1, 8 * mm),
        _field_table(
            styles,
            [
                ("Full name", name),
                ("Username", user.username),
                ("National ID", info.nationalId),
                ("Gender", info.gender),
                ("Department", info.department),
                ("Email", user.email),
                ("Address", _address_line(getattr(info, "address", None))),
                ("Reference", ref),
                ("Issued", _issued(info)),
            ],
        ),
        Spacer(1, 12 * mm),
    ]

    # Signature block: a line to sign over, and what the signature means.
    sign = Table(
        [
            ["", ""],
            [
                Paragraph("For the %s" % COMMITTEE, styles["label"]),
                Paragraph("Date", styles["label"]),
            ],
        ],
        colWidths=[70 * mm, 50 * mm],
        hAlign="LEFT",
    )
    sign.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
                ("TOPPADDING", (0, 0), (-1, 0), 14),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), 14),
            ]
        )
    )
    story.append(sign)
    story.append(Spacer(1, 10 * mm))
    story.append(
        Paragraph(
            "Quote reference %s in any correspondence about this registration."
            % ref,
            styles["sub"],
        )
    )

    note = "%s · %s · Issued %s" % (ORGANISATION, ref, _issued(info))
    return _build(story, "Proof of Registration - %s" % name, note)


# --------------------------------------------------------------------------- #
# The committee's record
# --------------------------------------------------------------------------- #


def member_record_pdf(info):
    """The full record, for the admin dashboard."""
    styles = _styles()
    user = info.user
    name = _full_name(user)
    ref = reference_for(info)
    address = getattr(info, "address", None)
    blood = getattr(info, "blood_donated", None)

    # Where this person sits in the family structure, if anywhere. Read through
    # the relations rather than the role field, which records their office.
    placements = []
    for attr, label in (("father", "Father"), ("mother", "Mother")):
        fam = getattr(user, attr, None)
        if fam is not None:
            placements.append("%s of %s" % (label, fam.name))
    try:
        for member in user.user.all().select_related("family"):
            placements.append("Child of %s" % member.family.name)
    except Exception:
        pass

    story = [
        _letterhead(styles),
        Spacer(1, 8 * mm),
        Paragraph("Member Record", styles["title"]),
        Paragraph("%s · Reference %s" % (name, ref), styles["kicker"]),
        Spacer(1, 9 * mm),
        _section(
            styles,
            "Member",
            [
                ("Full name", name),
                ("Username", user.username),
                ("Email", user.email),
                ("Committee role", user.role),
                ("Family placement", ", ".join(placements) if placements else "Not placed"),
            ],
        ),
        _section(
            styles,
            "Identification",
            [
                ("National ID", info.nationalId),
                ("Gender", info.gender),
                ("Department", info.department),
                ("Record reference", ref),
            ],
        ),
        _section(
            styles,
            "Address",
            [
                ("Province", getattr(address, "province", None)),
                ("District", getattr(address, "district", None)),
                ("Sector", getattr(address, "sector", None)),
                ("Cell", getattr(address, "cell", None)),
                ("Village", getattr(address, "village", None)),
            ],
        ),
        _section(
            styles,
            "Blood donation",
            [
                ("Has donated", getattr(blood, "donated", None)),
                ("Times donated", getattr(blood, "donated_times", None)),
            ],
        ),
        Paragraph(
            "This record contains personal data, including a national "
            "identification number. Handle and share it accordingly.",
            styles["sub"],
        ),
    ]

    note = "%s · Member record %s · Generated %s" % (ORGANISATION, ref, _issued(info))
    return _build(story, "Member Record - %s" % name, note)
