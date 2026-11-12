"""
A backup must bring the business back exactly: every table, every row, every field.

The "new computer" test fills InnKeeper with the whole sample business plus records the sample doesn't
create (fiscal documents, company invoices, online check-in, two currencies, two-step sign-in), exports a
full backup, wipes everything, restores it and compares the data row by row.
"""

import json
from decimal import Decimal

from django.apps import apps
from django.core import serializers
from django.test import TestCase

from apps.core import backup, sample
from apps.core.models import HotelSettings, clear_settings_cache

# Kept out of backups on purpose; every other model must be in backup.FULL_MODELS.
TRANSIENT = {
    "frontdesk.channelsyncstate": "sync bookkeeping, rebuilt by itself (it then sends everything once)",
    "outlets.printjob": "printer queue, kept a few days for retries",
}


def _snapshot() -> dict:
    out = {}
    for model in backup._models(backup.FULL_MODELS):
        rows = json.loads(serializers.serialize("json", model._default_manager.all().order_by("pk"), cls=backup._ExactEncoder))
        out[model._meta.label_lower] = rows
    return out


def _value(field, today, now):
    from django.db import models

    if field.choices:
        return field.choices[0][0]
    if isinstance(field, models.ForeignKey):
        return _one(field.related_model, today, now)
    if isinstance(field, (models.EmailField,)):
        return "test@example.com"
    if isinstance(field, (models.CharField, models.TextField, models.SlugField)):
        return ("t" + str(field.name))[: field.max_length or 20]
    if isinstance(field, models.DecimalField):
        return Decimal("1")
    if isinstance(field, (models.IntegerField, models.PositiveIntegerField, models.PositiveSmallIntegerField)):
        return 1
    if isinstance(field, models.BooleanField):
        return True
    if isinstance(field, models.DateTimeField):
        return now
    if isinstance(field, models.DateField):
        return today
    if isinstance(field, models.TimeField):
        return now.time().replace(microsecond=0)
    if isinstance(field, models.JSONField):
        return {"t": 1}
    if isinstance(field, models.BinaryField):
        return b"t"
    if isinstance(field, models.DurationField):
        from datetime import timedelta

        return timedelta(minutes=5)
    if isinstance(field, (models.FileField,)):
        return ""
    raise NotImplementedError(f"{field.model._meta.label}.{field.name}: {type(field).__name__}")


def _one(model, today, now):
    obj = model._default_manager.order_by("pk").first()
    if obj is not None:
        return obj
    from django.db import models

    kwargs = {}
    for f in model._meta.concrete_fields:
        if f.primary_key or f.auto_created:
            continue
        if isinstance(f, models.ForeignKey) and f.null:
            continue
        if f.has_default() or (f.null and not isinstance(f, models.ForeignKey)) or getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False):
            continue
        if f.blank and isinstance(f, (models.CharField, models.TextField)):
            continue
        kwargs[f.name] = _value(f, today, now)
    obj = model(**kwargs)
    obj.save()
    return obj


def fill_empty_tables():
    """At least one row in every backed-up table, so the round trip covers all of them."""
    from django.utils import timezone

    today, now = timezone.localdate(), timezone.now().replace(microsecond=456)  # sub-millisecond on purpose
    for model in backup._models(backup.FULL_MODELS):
        if not model._default_manager.exists():
            _one(model, today, now)


class BackupCoversEverythingTests(TestCase):
    def test_every_model_is_backed_up_or_listed_as_temporary(self):
        full = {m.lower() for m in backup.FULL_MODELS}
        missing = [
            m._meta.label_lower
            for m in apps.get_models()
            if m.__module__.startswith("apps.") and m._meta.label_lower not in full and m._meta.label_lower not in TRANSIENT
        ]
        self.assertEqual(missing, [], "add new models to backup.FULL_MODELS (or TRANSIENT with a reason)")


class NewComputerRestoreTests(TestCase):
    def setUp(self):
        from apps.accounts.models import User

        clear_settings_cache()
        self.boss = User.objects.create_superuser("owner", password="x-very-long-pass-2026")
        sample.load(self.boss)
        clear_settings_cache()
        self._extras()

    def _extras(self):
        """Records the sample business doesn't have."""
        from apps.finance.models import Folio, Payment
        from apps.fiscal.models import FiscalDocument
        from apps.frontdesk.models import Reservation, StayGuest
        from apps.outlets.models import Order

        hs = HotelSettings.load()
        hs.second_currency, hs.second_currency_symbol, hs.second_currency_rate = "ALL", "L", Decimal("0.0104")
        hs.bank_iban, hs.einvoice_due_days = "AL47212110090000000235698741", 21
        hs.save()
        res = Reservation.objects.order_by("pk").first()
        StayGuest.objects.create(reservation=res, first_name="Drita", last_name="Kola", document_number="T1")
        folio, _ = Folio.objects.get_or_create(reservation=res)
        folio.buyer_name, folio.buyer_nuis, folio.buyer_town = "Beta sh.p.k.", "M01234567C", "Durrës"
        folio.save()
        order = Order.objects.order_by("pk").first()
        if order:
            order.buyer_name, order.buyer_nuis = "Gama", "K31234567Z"
            order.save()
        Payment.objects.create(
            folio=folio, amount=Decimal("4.40"), method="cash", tendered=Decimal("4.41"),
            foreign_currency="ALL", foreign_amount=Decimal("424"), foreign_rate=Decimal("0.0104"),
        )
        FiscalDocument.objects.create(
            kind=FiscalDocument.Kind.INVOICE, folio=folio, inv_num="1/2026/ab123ab123", inv_ord_num=1,
            tcr_code="ab123ab123", operator_code="op123op123", business_unit="bu123bu123", software_code="sw123sw123",
            issue_datetime="2026-11-12T10:00:00+01:00", iic="A" * 32, iic_signature="B" * 512, total=Decimal("100.00"),
            type_of_inv="NONCASH", payload={"invoice": {"is_einvoice": True}}, status=FiscalDocument.Status.REGISTERED,
            fic="11111111-2222-3333-4444-555555555555", eic="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", einvoice_status="registered",
        )
        self.boss.totp_secret, self.boss.recovery_codes = "JBSWY3DPEHPK3PXP", ["hash1", "hash2"]
        self.boss.save()
        fill_empty_tables()


    def test_everything_comes_back_exactly(self):
        before = _snapshot()
        empty = [k for k, v in before.items() if not v]
        self.assertEqual(empty, [], "every table has data to restore")

        raw = backup.export_full()
        # Wipe the business, as on a new computer.
        for model in reversed(backup._models(backup.FULL_MODELS)):
            if model._meta.label_lower == "fiscal.fiscaldocument":
                model._default_manager.exclude(corrects=None).delete()
            model._default_manager.all().delete()
        clear_settings_cache()
        self.assertEqual(sum(len(v) for v in _snapshot().values()), 0)

        backup.restore_full(backup.read_file(raw))
        clear_settings_cache()
        after = _snapshot()
        for label, rows in before.items():
            self.assertEqual(len(after[label]), len(rows), label)
            self.assertEqual(after[label], rows, f"{label} differs after restore")

    def test_password_protected_backup_too(self):
        before = _snapshot()
        raw = backup.encrypt(backup.export_full(), "copy-password-2026")
        with self.assertRaises(backup.BackupError):
            backup.read_file(raw, "wrong-password")
        backup.restore_full(backup.read_file(raw, "copy-password-2026"))
        clear_settings_cache()
        after = _snapshot()
        for label, rows in before.items():
            for a, b in zip(rows, after[label]):
                if a != b:
                    diff = {k: (a["fields"][k], b["fields"].get(k)) for k in a["fields"] if a["fields"][k] != b["fields"].get(k)}
                    self.fail(f"{label} pk={a['pk']}: {diff}")
            self.assertEqual(len(after[label]), len(rows), label)

    def test_new_records_after_restore_get_new_numbers(self):
        from apps.frontdesk.models import Guest

        backup.restore_full(backup.read_file(backup.export_full()))
        top = Guest.objects.order_by("-pk").first().pk
        g = Guest.objects.create(first_name="New", last_name="Guest")
        self.assertGreater(g.pk, top)


class OlderBackupTests(TestCase):
    def test_a_backup_from_an_older_version_still_restores(self):
        """Older backups wrote times with milliseconds only (Django's own format)."""
        from apps.frontdesk.models import Guest

        Guest.objects.create(first_name="Old", last_name="Backup")
        data = []
        for model in backup._models(backup.FULL_MODELS):
            data.extend(json.loads(serializers.serialize("json", model._default_manager.all().order_by("pk"))))
        raw = backup._wrap("full", data)
        Guest.objects.all().delete()
        backup.restore_full(backup.read_file(raw))
        self.assertTrue(Guest.objects.filter(first_name="Old", last_name="Backup").exists())
