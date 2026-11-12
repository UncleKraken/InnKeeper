from django.test import SimpleTestCase
from django.utils import translation

from apps.core.templatetags.innkeeper import release_notes

NOTES = """## 9.9.9 — test

**Shqip**

- **Arka:** e re.

**English**

- **Till:** new.

### Install or update on Windows
1. Download it.
"""


class ReleaseNotesTests(SimpleTestCase):
    def test_only_the_readers_language_formatted(self):
        with translation.override("sq"):
            html = release_notes(NOTES)
        self.assertIn("<li><strong>Arka:</strong> e re.</li>", html)
        self.assertNotIn("Till", html)
        self.assertNotIn("**", html)
        self.assertNotIn("Download", html)
        with translation.override("en"):
            html = release_notes(NOTES)
        self.assertIn("<strong>Till:</strong>", html)
        self.assertNotIn("Arka", html)

    def test_html_is_escaped_and_only_https_links(self):
        html = release_notes("<script>x</script> [a](javascript:alert(1)) [b](https://example.com)")
        self.assertNotIn("<script>", html)
        self.assertNotIn('href="javascript', html)
        self.assertIn('href="https://example.com"', html)

    def test_plain_notes_still_shown(self):
        self.assertIn("<p>Bug fixes.</p>", release_notes("Bug fixes."))
