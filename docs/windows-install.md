# Installing InnKeeper on Windows — the “Windows protected your PC” message

**Shqip më poshtë ↓**

InnKeeper is free. Windows shows a warning the first time you run its installer because the
installer is not *code-signed*: signing certificates cost money every year, and Windows trusts new
programs only after many people have installed them. The warning does **not** mean anything is
wrong with the file. It only says Windows doesn't know the publisher yet.

## 1. Download only from the official page

<https://github.com/UncleKraken/InnKeeper/releases/latest> → under **Assets**, `InnKeeper-Setup-X.Y.Z.exe`.

Never install InnKeeper from another website, a USB stick from a stranger or a file sent in a chat.

### Optional: check the file is exactly the published one
On the release page, GitHub shows a **sha256** code next to the installer. On your computer open
**PowerShell** in the Downloads folder and run:

```powershell
Get-FileHash .\InnKeeper-Setup-X.Y.Z.exe -Algorithm SHA256
```

The long code must be the same as on GitHub. If it differs, delete the file and download again.

## 2. The browser may ask first

* **Edge:** “InnKeeper-Setup… isn't commonly downloaded” → click **…** → **Keep** → **Show more** → **Keep anyway**.
* **Chrome:** “… may be dangerous” / “uncommon” → **Keep**.

## 3. “Windows protected your PC” (SmartScreen)

1. Click **More info** (small link under the text).
2. The publisher shows as *Unknown publisher* — that is expected.
3. Click **Run anyway**.

Then the normal installer opens. Windows may ask “Do you want to allow this app to make changes?” → **Yes**.

## 4. If the antivirus deletes or blocks it

Programs packaged with Python (like InnKeeper) are sometimes flagged by mistake (“false positive”).

1. Check the file at <https://www.virustotal.com> (upload it): a few unknown engines out of ~70 is a false positive; many detections means don't install it.
2. Restore it from the antivirus quarantine / history and allow it.
3. If it keeps happening, add an exclusion for `C:\Program Files\InnKeeper` and `%LOCALAPPDATA%\InnKeeper` in the antivirus.

## 5. Updates

After the first install you don't need this again: **Settings → Updates → Update now** downloads the new
version from GitHub, checks its SHA-256 code and installs it without the browser or SmartScreen warnings.

## For IT people

* Files downloaded from the internet carry a “Mark of the Web”. Right-click the installer → **Properties** → tick **Unblock** → OK, or in PowerShell: `Unblock-File .\InnKeeper-Setup-X.Y.Z.exe`. Then it runs without the SmartScreen dialog.
* Silent install: `InnKeeper-Setup-X.Y.Z.exe /SILENT` (or `/VERYSILENT`). Data lives in `%LOCALAPPDATA%\InnKeeper` and is never removed by an update or uninstall.

---

# Instalimi i InnKeeper në Windows — mesazhi “Windows protected your PC”

InnKeeper është falas. Windows shfaq një paralajmërim herën e parë që hapni instaluesin, sepse
instaluesi nuk është i *nënshkruar dixhitalisht*: certifikatat e nënshkrimit kushtojnë çdo vit, dhe
Windows u beson programeve të reja vetëm pasi i kanë instaluar shumë njerëz. Paralajmërimi **nuk**
do të thotë që skedari ka problem. Thjesht Windows nuk e njeh ende botuesin.

## 1. Shkarkojeni vetëm nga faqja zyrtare

<https://github.com/UncleKraken/InnKeeper/releases/latest> → te **Assets**, `InnKeeper-Setup-X.Y.Z.exe`.

Mos e instaloni kurrë InnKeeper nga një faqe tjetër, nga një USB e panjohur ose nga një skedar i dërguar në chat.

### Opsionale: kontrolloni që skedari është pikërisht ai i publikuari
Në faqen e versionit, GitHub tregon një kod **sha256** pranë instaluesit. Në kompjuter hapni
**PowerShell** te dosja Downloads dhe shkruani:

```powershell
Get-FileHash .\InnKeeper-Setup-X.Y.Z.exe -Algorithm SHA256
```

Kodi i gjatë duhet të jetë i njëjtë me atë në GitHub. Nëse ndryshon, fshijeni skedarin dhe shkarkojeni sërish.

## 2. Shfletuesi mund të pyesë më parë

* **Edge:** “… isn't commonly downloaded” → klikoni **…** → **Keep** → **Show more** → **Keep anyway**.
* **Chrome:** “… may be dangerous” / “uncommon” → **Keep**.

## 3. “Windows protected your PC” (SmartScreen)

1. Klikoni **More info** (lidhja e vogël poshtë tekstit).
2. Botuesi shfaqet si *Unknown publisher* — kjo pritet.
3. Klikoni **Run anyway**.

Pastaj hapet instaluesi i zakonshëm. Windows mund të pyesë “Do you want to allow this app to make changes?” → **Yes**.

## 4. Nëse antivirusi e fshin ose e bllokon

Programet e paketuara me Python (si InnKeeper) ndonjëherë shënohen gabimisht (“false positive”).

1. Kontrollojeni skedarin te <https://www.virustotal.com> (ngarkojeni): disa motorë të panjohur nga ~70 është alarm i rremë; shumë zbulime do të thotë mos e instaloni.
2. Riktheni nga karantina / historiku i antivirusit dhe lejojeni.
3. Nëse përsëritet, shtoni përjashtim për `C:\Program Files\InnKeeper` dhe `%LOCALAPPDATA%\InnKeeper`.

## 5. Përditësimet

Pas instalimit të parë nuk ju duhet më: **Cilësimet → Përditësimet → Përditëso tani** e shkarkon versionin
e ri nga GitHub, kontrollon kodin SHA-256 dhe e instalon pa paralajmërimet e shfletuesit apo SmartScreen.

## Për njerëzit e IT-së

* Skedarët e shkarkuar nga interneti kanë një “Mark of the Web”. Klikim i djathtë mbi instaluesin → **Properties** → shënoni **Unblock** → OK, ose në PowerShell: `Unblock-File .\InnKeeper-Setup-X.Y.Z.exe`. Pastaj hapet pa dritaren e SmartScreen.
* Instalim i heshtur: `InnKeeper-Setup-X.Y.Z.exe /SILENT` (ose `/VERYSILENT`). Të dhënat janë te `%LOCALAPPDATA%\InnKeeper` dhe nuk fshihen kurrë nga një përditësim ose çinstalim.
