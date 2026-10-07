"""
Certificate handling and signatures for the Albanian fiscalization service.

* IIC (NSLF): the issuer signs a concatenation of invoice fields with RSA-SHA256 (PKCS#1 v1.5);
  IICSignature is that signature in hex, IIC is the MD5 of the signature bytes.
* Requests are XML-DSig signed: enveloped signature over the root element (Id="Request"), exclusive
  C14N, SHA-256 digest, RSA-SHA256, with the X.509 certificate in KeyInfo.
"""

import base64
import hashlib
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

DS = "http://www.w3.org/2000/09/xmldsig#"
EXC_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"


class CertificateError(Exception):
    pass


@dataclass
class Certificate:
    private_key: object
    certificate: object

    @classmethod
    def from_p12(cls, data: bytes, password: str) -> "Certificate":
        try:
            key, cert, _extra = pkcs12.load_key_and_certificates(data, (password or "").encode() or None)
        except (ValueError, TypeError) as e:
            raise CertificateError(str(e)) from e
        if key is None or cert is None:
            raise CertificateError("The file has no private key or certificate.")
        return cls(key, cert)

    @classmethod
    def from_settings(cls, hs) -> "Certificate":
        if not hs.fiscal_certificate:
            raise CertificateError("No certificate uploaded.")
        return cls.from_p12(base64.b64decode(hs.fiscal_certificate), hs.fiscal_certificate_password)

    @property
    def subject(self) -> str:
        return self.certificate.subject.rfc4514_string()

    @property
    def not_after(self):
        try:
            return self.certificate.not_valid_after_utc
        except AttributeError:  # older cryptography
            return self.certificate.not_valid_after

    def sign(self, data: bytes) -> bytes:
        return self.private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())

    def der_b64(self) -> str:
        return base64.b64encode(self.certificate.public_bytes(serialization.Encoding.DER)).decode()


def iic(cert: Certificate, fields: list[str]) -> tuple[str, str]:
    """Return (IIC, IICSignature) for the '|'-joined fields."""
    signature = cert.sign("|".join(fields).encode("utf-8"))
    return hashlib.md5(signature).hexdigest().upper(), signature.hex().upper()  # noqa: S324  (required by DPT)


def _c14n(node) -> bytes:
    return etree.tostring(node, method="c14n", exclusive=True, with_comments=False)


def sign_xml(root, cert: Certificate) -> None:
    """Append an enveloped XML-DSig <Signature> to `root` (which carries Id="Request")."""
    digest = base64.b64encode(hashlib.sha256(_c14n(root)).digest()).decode()
    sig = etree.SubElement(root, f"{{{DS}}}Signature", nsmap={None: DS})
    signed_info = etree.SubElement(sig, f"{{{DS}}}SignedInfo")
    etree.SubElement(signed_info, f"{{{DS}}}CanonicalizationMethod", Algorithm=EXC_C14N)
    etree.SubElement(signed_info, f"{{{DS}}}SignatureMethod", Algorithm=RSA_SHA256)
    ref = etree.SubElement(signed_info, f"{{{DS}}}Reference", URI=f"#{root.get('Id')}")
    transforms = etree.SubElement(ref, f"{{{DS}}}Transforms")
    etree.SubElement(transforms, f"{{{DS}}}Transform", Algorithm=ENVELOPED)
    etree.SubElement(transforms, f"{{{DS}}}Transform", Algorithm=EXC_C14N)
    etree.SubElement(ref, f"{{{DS}}}DigestMethod", Algorithm=SHA256)
    etree.SubElement(ref, f"{{{DS}}}DigestValue").text = digest
    value = base64.b64encode(cert.sign(_c14n(signed_info))).decode()
    etree.SubElement(sig, f"{{{DS}}}SignatureValue").text = value
    key_info = etree.SubElement(sig, f"{{{DS}}}KeyInfo")
    x509 = etree.SubElement(key_info, f"{{{DS}}}X509Data")
    etree.SubElement(x509, f"{{{DS}}}X509Certificate").text = cert.der_b64()


def verify_xml(root, public_key) -> bool:
    """Check an enveloped signature made by sign_xml (used by the tests)."""
    import copy

    doc = copy.deepcopy(root)
    sig = doc.find(f"{{{DS}}}Signature")
    signed_info = sig.find(f"{{{DS}}}SignedInfo")
    digest = signed_info.find(f".//{{{DS}}}DigestValue").text
    value = base64.b64decode(sig.find(f"{{{DS}}}SignatureValue").text)
    public_key.verify(value, _c14n(signed_info), padding.PKCS1v15(), hashes.SHA256())
    doc.remove(sig)
    return base64.b64encode(hashlib.sha256(_c14n(doc)).digest()).decode() == digest
