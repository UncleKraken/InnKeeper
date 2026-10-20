"""InnKeeper itself: where it comes from, how to get help, and how to recommend it to another business."""

from urllib.parse import quote

from django.shortcuts import render
from django.utils.translation import gettext as _

from django.contrib.auth.decorators import login_required

# Where InnKeeper lives. Change these in one place if the project gets its own domain or support contact.
WEBSITE = "https://unclekraken.github.io/InnKeeper/"
SOURCE = "https://github.com/UncleKraken/InnKeeper"
DOWNLOAD = "https://github.com/UncleKraken/InnKeeper/releases/latest"
SUPPORT = "https://github.com/UncleKraken/InnKeeper/issues"


def share_text() -> str:
    return _(
        "I use InnKeeper to run my business: rooms, restaurant and bar, staff and the fiscal receipts, in Albanian and "
        "English, free. Have a look: %(url)s"
    ) % {"url": WEBSITE}


@login_required
def about(request):
    from apps import __version__
    from apps.outlets.menu import qr_svg

    text = share_text()
    return render(
        request,
        "core/about.html",
        {
            "version": __version__,
            "website": WEBSITE,
            "source": SOURCE,
            "download": DOWNLOAD,
            "support": SUPPORT,
            "whatsapp": f"https://wa.me/?text={quote(text)}",
            "email_link": f"mailto:?subject={quote('InnKeeper')}&body={quote(text)}",
            "share_text": text,
            "qr": qr_svg(WEBSITE),
        },
    )
