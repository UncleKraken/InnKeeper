# Changelog

## 2.5.1 — audit fixes before go-live

**Shqip**

- **Paratë:** një prekje e dyfishtë në “Merr para” nuk regjistron më dy pagesa; netët e anuluara nuk shtohen sërish nga auditi i natës; në grupet me një faturë, asnjë dhomë nuk paguhet dy herë dhe dhoma kryesore e anuluar nuk mbledh faturat e të tjerëve; tepricat duhet të kthehen para largimit; anulimet e ditëve të kaluara dalin në ditën e anulimit dhe nuk ndryshojnë mbylljet e ditëve; pagesat online janë në mbylljen e ditës; faturat e mosparaqitjeve mbyllen.
- **Fiskalizimi:** zbritjet japin gjithmonë totalin e saktë; pjesa e paguar në tavolinë kur pjesa tjetër kalon në dhomë merr kupon fiskal; shitjet pa kupon (p.sh. certifikatë e gabuar) fiskalizohen vetë kur rregullohet problemi, me paralajmërim në panel; paralajmërim 30 ditë para skadimit të certifikatës; një dokument me problem nuk bllokon të tjerët; kursi i këmbimit për çmimet në EUR; deklarimi i arkës në sistemin provë nuk vlen për punën reale.
- **Restoranti & bari:** zbritja mbetet brenda kufirit kur hiqen artikuj; faturat me zbritje 100% mbyllen; bashkimi i tavolinave ruan zbritjen; artikujt e mbaruar nuk shtohen me “+”; paralajmërim kur printeri i kuzhinës nuk printon.
- **Recepsioni:** ndryshimi i shënimeve nuk ndryshon çmimet e kanaleve; dhomat jashtë funksionit nuk rezervohen; një kalendar bosh nga kanali nuk anulon rezervimet; largimi me vonesë nuk mbivendoset me mysafirin tjetër.
- **Siguria & Windows:** bllokim pas fjalëkalimeve të gabuara edhe për /admin; adresa e vërtetë e vizitorit pas Cloudflare Tunnel; cookies të sigurta mbi HTTPS; eksportet CSV të sigurta për Excel; s'mund të hapen dy InnKeeper njëherësh; kopje e bazës së të dhënave para çdo përditësimi; ndryshimet e cilësimeve vlejnë menjëherë edhe për punët në sfond; asnjë “database is locked” kur dy veta ruajnë njëkohësisht.

**English**

- **Money:** a double tap on “Take cash” no longer records two payments; voided room nights aren't posted again by the night audit; on one-bill groups no room is charged twice and a cancelled main room no longer collects the others' bills; overpayments must be refunded before check-out; voids of past days count on the day they're made, so closed days never change; online payments are in the day close; no-show bills close.
- **Fiscalization:** discounts always give the exact total; the part paid at the table when the rest goes to a room gets a fiscal receipt; sales left without a receipt (e.g. wrong certificate password) are fiscalized automatically once fixed, with a dashboard warning; a warning 30 days before the certificate expires; one bad document no longer blocks the others; exchange rate for prices in EUR; test-system cash reports don't count once live.
- **Restaurant & bar:** discounts stay within the staff limit when items are removed; 100% discounted bills can be closed; merging tables keeps the discount; sold-out items can't be increased; a warning when a kitchen printer fails.
- **Front desk:** editing notes keeps channel prices; out-of-order rooms can't be booked; one empty channel calendar no longer cancels bookings; late check-out never overlaps the next guest.
- **Security & Windows:** login lockout also covers /admin; real visitor address behind Cloudflare Tunnel; secure cookies over HTTPS; Excel-safe CSV exports; only one InnKeeper can run; a copy of the database before every update; settings changes reach background jobs at once; no more “database is locked” when two people save at the same time.

### Install or update on Windows
1. Download **InnKeeper-Setup-2.5.1.exe** below and run it. Updating keeps all your data; a copy of the database is made first.
2. Windows may show "Windows protected your PC" because the installer is not yet code-signed. Click **More info → Run anyway**.

## 2.5.0 — fiscalization and Excel import

**Shqip**

- **Fiskalizimi direkt me tatimet (DPT):** çdo faturë e paguar e restorantit/barit dhe çdo faturë mysafiri nënshkruhet me certifikatën e biznesit dhe regjistrohet te tatimet. Kuponi dhe fatura shfaqin NSLF, NIVF dhe kodin QR të verifikimit. TVSH e veçantë për akomodimin, fatura korrigjuese për anulimet, deklarimi ditor i arkës, punë pa internet me dërgim automatik brenda 48 orëve, sistemi provë i tatimeve. Faqja e re *Financa → Fiskalizimi* tregon çdo dokument dhe gjendjen e tij.
- **Importi nga Excel:** menuja, stoku dhe mysafirët nga një skedar CSV, me parapamje para ruajtjes dhe emra kolonash shqip ose anglisht.
- **Udhëzuesi:** seksione të reja për fiskalizimin, importin dhe një listë kontrolli për fillimin e punës.

**English**

- **Direct fiscalization with the tax authority (DPT):** every paid restaurant/bar bill and every guest bill is signed with the business's certificate and registered with the tax authority. Receipts and invoices show the NSLF, NIVF and verification QR code. Separate accommodation VAT, corrective invoices for voids, daily cash deposit, offline mode with automatic resend within 48 hours, and the tax authority's test system. The new *Finance → Fiscal* page lists every document and its status.
- **Import from Excel:** menu, stock and guests from a CSV file, with a preview before saving and Albanian or English column names.
- **Guide:** new sections on fiscalization, import and a go-live checklist.

### Install or update on Windows
1. Download **InnKeeper-Setup-2.5.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not yet code-signed. Click **More info → Run anyway**.

> Fiscalization is off until you enable it in Settings. Keep the tax authority's test system on until your test sales show as Registered.

## 2.4.0 — channel manager and card payments

**Shqip**

- **Menaxheri i kanaleve (Channex):** lidhje e plotë me Booking.com, Airbnb, Expedia dhe mbi 50 kanale nëpërmjet Channex, një partner i certifikuar. InnKeeper dërgon dhomat e lira, çmimin e çdo nate dhe qëndrimin minimal sa herë ndryshon diçka, dhe merr çdo minutë rezervimet e reja, të ndryshuara dhe të anuluara me emrin e mysafirit dhe çmimin. Pa mbirezervime: problemet shfaqen me të kuqe.
- **Pagesat me kartë (POK ose Paysera):** mysafirët paguajnë parapagimin me kartë direkt nga faqja e rezervimit; recepsioni krijon dhe dërgon lidhje pagese për çdo shumë. Pagesat konfirmohen te ofruesi dhe shfaqen vetë në faturën e mysafirit.
- Përmirësime: të dhënat sekrete (çelësat API, fjalëkalimet) nuk përfshihen në eksportin e cilësimeve.

**English**

- **Channel manager (Channex):** a full connection to Booking.com, Airbnb, Expedia and 50+ channels through Channex, a certified partner. InnKeeper sends free rooms, the price of every night and minimum stays whenever something changes, and fetches new, changed and cancelled bookings every minute with the guest's name and price. No overbooking: problems are shown in red.
- **Card payments (POK or Paysera):** guests pay the deposit by card straight from the booking page; reception creates and sends payment links for any amount. Payments are confirmed with the provider and appear on the guest's bill by themselves.
- Improvements: secrets (API keys, passwords) are left out of the settings export.

### Install or update on Windows
1. Download **InnKeeper-Setup-2.4.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not yet code-signed. Click **More info → Run anyway**.

> Receipts and invoices are internal documents, not fiscal receipts. Fiscalisation is planned for a later version.

## 2.3.0 — stock, groups, channel calendars and guest register

**Shqip**

- **Stoku & inventari:** artikuj stoku dhe furnitorë, receta për çdo artikull të menusë (shitjet dhe kalimet në dhomë e heqin stokun automatikisht, anulimet e kthejnë), furnizime me çmim mesatar dhe shpenzim automatik, humbje/thyerje, numërime stoku me diferencat, paralajmërim për stok të ulët, raport i kostos së shitjeve.
- **Rezervime në grup:** disa dhoma njëherësh, një faturë e përbashkët (dhoma kryesore paguan për të gjithë), regjistrim/largim i të gjithë grupit me një buton.
- **Booking.com, Airbnb e kanale të tjera:** sinkronizim i kalendarëve me lidhje iCal në të dy drejtimet, çdo 15 minuta, me paralajmërim për rezervime të dyfishta.
- **Regjistri i mysafirëve:** lista e mysafirëve sipas datës me shtetësinë dhe dokumentin, vetëm të huajt nëse duhet, për printim ose Excel; kujtesë për ID-në në regjistrim.
- Rregullime: kopjet rezervë tani përfshijnë stacionet, printerët, sezonet dhe porositë e kuzhinës; eksporti i cilësimeve përfshin edhe stokun, recetat dhe kalendarët e kanaleve.

**English**

- **Stock & inventory:** stock items and suppliers, recipes per menu item (sales and room charges take stock automatically, voided receipts put it back), deliveries with average cost and an optional expense, waste/breakage, stock counts with variance, low-stock alerts, cost of sales report.
- **Group bookings:** several rooms at once, one shared bill (the main room pays for everyone), check the whole group in or out with one button.
- **Booking.com, Airbnb and other channels:** two-way calendar sync with iCal links, every 15 minutes, with warnings instead of overbooking.
- **Guest register:** guests by date with nationality and document, foreigners only if required, to print or open in Excel; ID reminder at check-in.
- Fixes: full backups now include stations, printers, seasons and kitchen tickets; the settings export also carries stock items, recipes and channel calendars.

### Install or update on Windows
1. Download **InnKeeper-Setup-2.3.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not yet code-signed. Click **More info → Run anyway**.

> Receipts and invoices are internal documents, not fiscal receipts. Fiscalisation is planned for a later version.

## 2.2.0 — kitchen screens, printers and online booking

**Shqip**

- **Ekranet e kuzhinës & barit:** kamarieri shtyp *Dërgo* dhe porosia shfaqet menjëherë në tabletin ose televizorin e kuzhinës/barit, me tingull dhe kohën e pritjes. *Fillo → Gati*, dhe tavolina merr pikë të gjelbër te kamarieri. Rol i ri: *Kuzhina & bari*.
- **Printerë termikë:** printerë rrjeti (IP) ose USB në Windows. Kupona dhe fatura direkt në printer, porosi në kuzhinë/bar, hapja e sirtarit të parave me pagesat cash, printim provë dhe riprovim i printimeve të dështuara.
- **Sezonet & çmimet:** çmime sipas periudhës (përqindje ose çmim fiks për lloj dhome), qëndrim minimal; çmimi llogaritet natë për natë dhe fatura ndahet sipas çmimit.
- **Rezervim online:** faqe publike rezervimi në shqip dhe anglisht me foto të dhomave, çmimin total dhe parapagim me transfertë bankare. Kërkesat konfirmohen ose refuzohen nga recepsioni; mysafiri merr email.
- **Email:** konfigurim SMTP (p.sh. Gmail) për konfirmimet dhe njoftimet, me email provë.
- Përmirësime: kamarieri mund të anulojë një porosi kur të gjithë artikujt e dërguar janë hequr.

**English**

- **Kitchen & bar screens:** waiters press *Send* and the order appears straight away on the kitchen or bar tablet/TV, with a sound and the waiting time. *Start → Ready*, and the table gets a green dot on the waiter's floor plan. New role: *Kitchen & bar*.
- **Thermal printers:** network (IP) printers, or USB printers installed in Windows. Bills and receipts straight to the printer, order tickets to kitchen/bar, cash drawer opens on cash payments, test print and retry of failed prints.
- **Seasons & prices:** prices by period (percentage or fixed price per room type), minimum stay; stays are priced night by night and the bill is split by price.
- **Online booking:** a public booking page in Albanian and English with room photos, total price and a deposit by bank transfer. Reception confirms or declines requests; the guest gets an email.
- **Email:** SMTP settings (e.g. Gmail) for confirmations and alerts, with a test email.
- Fix: staff can cancel an order once every item that was sent to the kitchen has been removed.

### Install or update on Windows
1. Download **InnKeeper-Setup-2.2.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not yet code-signed. Click **More info → Run anyway**.

> Receipts and invoices are internal documents, not fiscal receipts. Fiscalisation is planned for a later version.

## 2.1.0 — first public release

**Shqip** · InnKeeper për hotele, bujtina, restorante, bare dhe kafene.

- Udhëzues konfigurimi: zgjidhni hotel, bujtinë ose restorant/bar dhe aplikacioni aktivizon vetëm atë që ju duhet
- Recepsioni: tabela e dhomave, rezervime, hyrje/largime, llogaria e mysafirit, fatura me numër
- Restorant, bar & shërbime: plan salle me tërheqje, zbritje, pagesa të ndara, kusuri, kalim në dhomë, kupona me logo, menu me kod QR
- Pastrimi dhe mirëmbajtja
- Financa: të ardhura, shpenzime, fitimi, mbyllja e ditës (raporti Z), shitjet
- Kopje rezervë dhe kalim në kompjuter tjetër; kopje automatike çdo ditë
- Shqip dhe anglisht, udhëzues brenda aplikacionit

**English** · InnKeeper for hotels, guesthouses, restaurants, bars and cafés.

- Setup wizard: choose hotel, guesthouse or restaurant/bar and only the parts you need are switched on
- Front desk: room rack, reservations, check-in/out, guest bills, numbered invoices
- Restaurant, bar & services: drag-and-drop floor plan, discounts, split payments, change calculator, charge to room, receipts with logo, QR menu
- Housekeeping and maintenance
- Finance: revenue, expenses, profit, day close (Z report), sales reports
- Backups and moving to a new computer; automatic daily backups
- Albanian and English, built-in user guide

### Install on Windows
1. Download **InnKeeper-Setup-2.1.0.exe** below and run it.
2. Windows may show "Windows protected your PC" because the installer is not yet code-signed. Click **More info → Run anyway**.
3. Open InnKeeper from the desktop icon, create your manager account and follow the setup wizard.

Your data is stored in `%LOCALAPPDATA%\InnKeeper` and is kept when you update or uninstall.

> Receipts and invoices are internal documents, not fiscal receipts.
