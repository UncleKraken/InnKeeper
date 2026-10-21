# Changelog

## 2.29.0 — online check-in

**Shqip**

- **Check-in online:** para se të mbërrijnë, mysafirët hapin një link privat (në email-in e mbërritjes, në faqen e rezervimit, ose me WhatsApp nga rezervimi) dhe shkruajnë të dhënat e kartës së identitetit ose pasaportës për të gjithë personat në dhomë, si dhe orën e mbërritjes. Në mbërritje recepsioni thjesht jep çelësin.
- **Të gjithë personat në dhomë**, jo vetëm mysafiri kryesor: te rezervimi, *Mysafirët e këtij qëndrimi* i lejon recepsionit t'i shkruajë vetë (për ata pa rezervim).
- **Regjistri i mysafirëve** liston tani çdo person, me çfarë mungon ende për secilin, edhe në Excel dhe CSV.
- Paneli dhe rezervimi tregojnë kush ka bërë check-in online dhe orën e pritshme të mbërritjes.
- Linku punon derisa mysafiri të bëjë check-in, nuk shfaq numrat e dokumenteve të ruajtur më parë, dhe kërkon adresën publike. Mund ta çaktivizoni te *Cilësimet → Mesazhet për mysafirët*.

**English**

- **Online check-in:** before arriving, guests open a private link (in the arrival email, on the booking page, or sent by WhatsApp from the reservation) and enter the ID card or passport details of everyone in the room, and their expected arrival time. At arrival, reception just hands over the key.
- **Everyone in the room**, not only the main guest: on the reservation, *Guests in this stay* lets reception enter them for walk-ins.
- **The guest register** now lists every person, with what is still missing for each, in Excel and CSV too.
- The dashboard and the reservation show who checked in online and the expected arrival time.
- The link works until the guest checks in, never shows ID numbers stored earlier, and needs the public web address. Switch it off under *Settings → Guest messages*.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.29.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.28.1 — clearer Albanian and English

**Shqip**

- **Përkthimi shqip u rishikua i gjithi** (rreth 2 800 tekste): u rregulluan gramatika, fjalët e paqarta dhe mospërputhjet. Disa shembuj:
  - Butonat e recepsionit thonë tani **Bëj check-in** dhe **Bëj check-out**, në vend të “Regjistro hyrjen / largimin”, që ngatërroheshin me hyrjen e stafit në punë.
  - “Order” te porositë e mysafirëve nga tavolina shfaqet si **Porosia** (më parë dilte gabimisht “Renditja”).
  - Të njëjtat fjalë kudo: *zhvendos* (tavolinën, mysafirin), *niveli minimal* i stokut, *tema* e email-it, *ju lutemi*, dhe forma e sjellshme (*ju*) në vend të *ti*.
- **Udhëzuesi** (Ndihmë) u përditësua me emrat e rinj të butonave, dhe tani përmend rolin *Kuzhina & bari* dhe pagesën e parapagimit me kartë.
- **Telefonat Android:** udhëzimi thotë të zgjidhni *Create shortcut* (“Install” në Chrome kërkon adresë https).
- **Faqja e InnKeeper dhe udhëzimet e instalimit** u rishikuan në të dy gjuhët; dosja e programit tregohet saktë (*Program Files (x86)*).

**English**

- **The whole Albanian translation was reviewed** (about 2,800 texts): grammar, unclear words and inconsistencies fixed. For example:
  - Front-desk buttons now say **Bëj check-in / Bëj check-out** instead of wording that was easy to confuse with staff clocking in.
  - “Order” on guests' table orders now shows as *Porosia*; it wrongly showed the word for sort order.
  - The same words everywhere for moving tables and guests, the stock minimum level, the email subject, and the polite form throughout.
- **English texts:** a few help texts reworded, and the help guide now mentions the *Kitchen & bar* role and card deposits.
- **Android phones:** the tip now says to choose *Create shortcut* (Chrome's “Install” needs an https address).
- **The InnKeeper website and install guide** were reviewed in both languages; the program folder is now named correctly (*Program Files (x86)*).

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.28.1.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.28.0 — phones and tablets connect easier

**Shqip**

- **Kodi QR në dritaren e InnKeeper:** stafi skanon kodin me telefon ose tablet dhe InnKeeper hapet menjëherë, pa shkruar adresën. Nëse ruteri i jep kompjuterit adresë të re (p.sh. pas ndërprerjes së energjisë), dritarja e përditëson vetë adresën dhe kodin.
- **Muri mbrojtës i Windows:** instaluesi e lejon vetë InnKeeper në rrjet, vetëm për pajisjet e rrjetit lokal (dhe Tailscale), kështu që telefonat dhe tabletët lidhen pa pyetjen e Windows-it. Hiqet kur çinstalohet InnKeeper.
- Adresa për telefonat gjendet tani edhe kur kompjuteri nuk ka internet.
- **Cilësimet → Telefonat, tabletët dhe qasja nga jashtë:** kodi për të skanuar, hapat (Wi-Fi, “Shto në ekranin kryesor”, hyrja ose arka e përbashkët me PIN) dhe çfarë të bëni kur një pajisje nuk lidhet (muri mbrojtës, gjumi i kompjuterit, rezervimi i adresës te ruteri).
- Pas konfigurimit të parë, hapi i ri “Lidhni telefonat dhe tabletët”.

**English**

- **QR code in the InnKeeper window:** staff scan it with a phone or tablet and InnKeeper opens, with no address to type. If the router gives the computer a new address (after a power cut, say), the window updates the address and the code by itself.
- **Windows Firewall:** the installer now allows InnKeeper on the network, only for devices on the local network (and Tailscale), so phones and tablets connect without Windows asking. The rule is removed on uninstall.
- The address for phones is now found even when the computer has no internet.
- **Settings → Phones, tablets & remote access:** a code to scan, the steps (Wi-Fi, Add to Home Screen, sign-in or a shared till with PINs) and what to check when a device can't connect (firewall, the computer going to sleep, reserving the address in the router).
- After the first setup, a new “Connect phones and tablets” step.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.28.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.27.1 — fixes from a full check

**Shqip**

- **Raporti i përdorimit të stokut** nuk hapej pasi ishte bërë një transferim malli mes bizneseve. U rregullua, dhe raporti tani tregon edhe sasinë e dërguar.
- **Roli i financës (kontabilisti)** nuk sheh më linke drejt faqeve të recepsionit që nuk i hap; mund të shohë dhe printojë kuponat e restorantit nga libri i llogarive.
- Listat e pikave të shitjes, printerëve, fushatave, furnizimeve, numërimeve dhe furnitorëve mbajnë gjithmonë të njëjtën renditje.
- Fatura dhe kartat QR për printim nuk dalin më jashtë ekranit në telefon.

**English**

- **The stock usage report** wouldn't open once goods had been transferred between businesses. Fixed, and the report now shows the quantity sent too.
- **The finance role (accountant)** no longer sees links to front-desk pages it can't open; it can view and print restaurant receipts from the ledger.
- The lists of outlets, printers, campaigns, deliveries, counts and suppliers always keep the same order.
- The printable invoice and QR card sheets no longer run off the screen on phones.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.27.1.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.27.0 — spread the word

**Shqip**

- **Rreth InnKeeper** (në menu): versioni, udhëzuesi, faqja e InnKeeper, shkarkimi, ku të njoftoni një problem, dhe **rekomandimi te një biznes tjetër** me WhatsApp, email ose një kod QR.
- **“Bërë me InnKeeper”:** një link i vogël në fund të faqeve publike (rezervimi, menuja, porositë nga tavolina, regjistrimi). Mund ta fikni te *Cilësimet → Kuponat & faturat*.
- **Faqja e InnKeeper:** https://unclekraken.github.io/InnKeeper/ — në shqip dhe anglisht, me pamje nga programi dhe butonin e shkarkimit.

**English**

- **About InnKeeper** (in the menu): the version, the guide, the InnKeeper website, the download, where to report a problem, and **recommending it to another business** by WhatsApp, email or a QR code.
- **“Made with InnKeeper”:** a small link at the bottom of public pages (booking, menu, table orders, sign-up). Turn it off under *Settings → Receipts & invoices*.
- **InnKeeper website:** https://unclekraken.github.io/InnKeeper/ — in Albanian and English, with screenshots and the download button.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.27.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.26.0 — contacts and marketing

**Shqip**

- **Kontaktet** (*Menaxhimi → Kontaktet & marketingu*): të gjithë ata që mund t'i arrini — mysafirët, kartat e besnikërisë, llogaritë e klientëve, rezervimet e tavolinave — në një listë, pa dyfishime, me kërkim, etiketa dhe eksport në Excel/CSV.
- **Pëlqimi sipas ligjit:** oferta vetëm për ata që kanë pranuar, me datën dhe mënyrën e pëlqimit të ruajtura. Mënyrat: kutia në rezervimin online, faqja e regjistrimit me poster QR, ose recepsioni me një shënim. Fshirja e të dhënave me kërkesë.
- **Fushatat me email:** ofertë ose lajm për të gjithë, për shqipfolësit ose anglishtfolësit, për mysafirët e vitit të fundit ose sipas etiketës; provë te vetja; dërgim një nga një në sfond; çregjistrim me një klik në çdo email.
- **Numrat për WhatsApp:** për listat e transmetimit në WhatsApp Business (falas).

**English**

- **Contacts** (*Management → Contacts & marketing*): everyone you can reach — guests, loyalty cards, customer accounts, table bookings — in one list without duplicates, with search, tags and Excel/CSV export.
- **Consent as the law asks:** offers only to people who agreed, with the date and way they agreed kept. Ways to agree: the box on the online booking form, the sign-up page with its QR poster, or reception with a note. Erase someone's data on request.
- **Email campaigns:** an offer or news to everyone, to Albanian or English speakers, to guests from the last year or by tag; a test to yourself; sent one by one in the background; one-click unsubscribe in every email.
- **Numbers for WhatsApp:** for broadcast lists in WhatsApp Business (free).

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.26.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.25.0 — payroll: optional holiday pay, your own pay period

**Shqip**

- **Shtesa për festat zyrtare është tani sipas dëshirës** dhe e fikur fillimisht: shumë hotele dhe bare të hapura çdo ditë nuk e paguajnë veçmas. Ndizeni te *Listëpagesa → Shtesat*, dhe te *Festat zyrtare* shënoni vetëm ditët që paguani me shtesë.
- **Periudha e pagës:** nëse paguani p.sh. nga 26 deri më 25, vendosni *Periudha e pagës fillon më 26*. Listëpagesa, paga mujore dhe orët jashtë orarit ndjekin këtë periudhë.
- Kujdes: nëse përdorët shtesën e festave në 2.20–2.24, ndizeni përsëri te *Shtesat*.

**English**

- **Public holiday extra pay is now optional** and off to start with: many hotels and bars open every day don't pay it separately. Turn it on under *Payroll → Extras*, and under *Public holidays* tick only the days you pay extra for.
- **Pay period:** if you pay from, say, the 26th to the 25th, set *Pay period starts on day* to 26. The payroll, monthly salaries and overtime follow that period.
- Note: if you used holiday extra pay in 2.20–2.24, turn it on again under *Extras*.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.25.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.24.0 — group month report and stock transfers

**Shqip**

- **Raporti mujor i grupit** (*Pamja e grupit → Raporti mujor*): muaji i çdo biznesi krah për krah — shitjet, paratë e marra, shpenzimet, fitimi, TVSH, taksa e turizmit, zbritjet, kuponat, zënia e dhomave — me totale dhe Excel. Totali del vetëm kur janë përgjigjur të gjitha bizneset, që të mos jetë i pjesshëm.
- **Transferimi i mallit mes bizneseve** (*Stoku → Transferimet*): dërguesi e heq mallin nga stoku dhe merr një kod; marrësi e ngjit, kontrollon artikujt dhe e fut në stok me të njëjtën kosto. Çdo kod merret vetëm një herë. Asnjë biznes nuk mund të ndryshojë të dhënat e tjetrit.

**English**

- **Group month report** (*Group overview → Month report*): each business's month side by side — sales, money received, expenses, profit, VAT, tourist tax, discounts, receipts, room occupancy — with totals and Excel. A total appears only when every business answered, so it's never partial.
- **Moving goods between businesses** (*Stock → Transfers*): the sender takes the goods out of stock and gets a code; the receiver pastes it, checks the items and takes them into stock at the same cost. Each code can be received once. No business can change another's data.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.24.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.23.0 — breakfast and minibar

**Shqip**

- **Mëngjesi:** çdo mëngjes, *Recepsioni → Mëngjesi* liston mysafirët që fjetën mbrëmë, me sa veta janë dhe nëse mëngjesi është në çmim. Stafi i restorantit shënon çdo dhomë si të shërbyer; për ata pa mëngjes të përfshirë shtohet automatikisht në faturë. Çdo rezervim ka *Me mëngjes të përfshirë*; parazgjedhja dhe çmimi te *Cilësimet → Mëngjesi*.
- **Minibari:** në tabelën e pastrimit, dhomat e zëna kanë butonin *Minibar* — numëroni çfarë mungon dhe shkon në faturën e mysafirit, me stokun e përditësuar.
- Biznesi shembull ka minibar dhe mëngjes.

**English**

- **Breakfast:** each morning, *Front desk → Breakfast* lists the guests who slept here last night, how many they are and whether breakfast is in their price. Restaurant staff mark each room as served; for guests without it included, it goes on their bill automatically. Each booking has *Breakfast included*; the default and the price are in *Settings → Breakfast*.
- **Minibar:** on the housekeeping board, occupied rooms have a *Minibar* button — count what's missing and it goes on the guest's bill, with stock updated.
- The sample business has a minibar and breakfast.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.23.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.22.0 — pay by card from the table

**Shqip**

- **Pagesa nga tavolina:** faqja QR e tavolinës tregon faturën e hapur dhe sa ka mbetur, me zgjedhje bakshishi (pa, 5, 10, 15%), dhe klienti paguan me kartë te POK ose Paysera. Pagesa regjistrohet në faturë, bakshishi shkon te stafi, dhe fatura mbyllet me kuponin fiskal kur paguhet e gjitha.
- Nëse fatura ndryshoi ndërkohë (p.sh. një pjesë u pagua me para), pagesa me kartë nuk humbet: çdo tepricë shënohet te *Porositë nga tavolina* për ta kthyer.
- Ndizeni për çdo pikë: *Klientët paguajnë faturën me kartë nga tavolina*.

**English**

- **Pay from the table:** the table's QR page shows the open bill and what's left, with a tip choice (none, 5, 10, 15%), and the guest pays by card through POK or Paysera. The payment goes on the bill, the tip to the staff, and the bill closes with its fiscal receipt once fully paid.
- If the bill changed in the meantime (say part was paid in cash), the card payment isn't lost: anything over is flagged under *Table orders* for a refund.
- Turn it on per outlet: *Guests can pay the bill by card from the table*.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.22.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.21.0 — leave and shift swaps

**Shqip**

- **Lejet:** stafi kërkon leje nga telefoni te *Orët e mia* (vjetore, mjekësore, pa pagesë, tjetër) dhe sheh ditët e mbetura të vitit. Menaxherët miratojnë ose refuzojnë te *Stafi → Kërkesa*, duke parë ditët e mbetura dhe turnet e planifikuara. Leja e miratuar del në orar dhe nuk llogaritet si mungesë.
- **Ndërrimi i turneve:** "Mund ta marrësh këtë turn?" — kolegu pranon, menaxheri miraton, dhe turni kalon në orar.
- Numra të kuq në menu për kërkesat në pritje. Ditët e lejes vjetore për çdo person te të dhënat e punonjësit (20 si parazgjedhje).

**English**

- **Leave:** staff ask for leave from their phone under *My hours* (annual, sick, unpaid, other) and see the days they have left this year. Managers approve or decline under *Staff → Requests*, seeing the days left and any planned shifts. Approved leave shows on the schedule and isn't counted as a no-show.
- **Shift swaps:** "Can you take this shift?" — the colleague agrees, a manager approves, and the shift moves on the schedule.
- Red counts in the menu for waiting requests. Annual leave days per person in the employee details (20 by default).

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.21.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.20.0 — payroll from the clock-ins

**Shqip**

- **Listëpagesa** (*Stafi → Listëpagesa*): paga bruto e çdo personi nga hyrjet dhe daljet e muajit — me orë, ose pagë mujore për ditët e punësimit — me shtesat për orët jashtë orarit (mbi orët e kontratës në javë), punën e natës (22:00–06:00) dhe festat zyrtare. Përqindjet i vendosni vetë sipas kontratave.
- **Festat zyrtare:** një prekje plotëson festat me datë fikse dhe të dyja Pashkët për vitin; ditët e Bajramit i shtoni kur shpallen.
- **Shpërblime dhe paradhënie** për muajin, **miratimi i muajit** (shifrat ruhen edhe nëse ndryshon një hyrje më vonë), printim dhe Excel me IBAN-in për bankën dhe kontabilistin.
- Kontributet dhe tatimi mbi të ardhurat mbeten te kontabilisti: ndryshojnë çdo vit dhe një shifër e gabuar në pagë është më keq se asnjë.

**English**

- **Payroll** (*Staff → Payroll*): each person's gross pay from the month's clock-ins — hourly, or a monthly salary for the days employed — with extras for overtime (over the contract hours in a week), night work (22:00–06:00) and public holidays. You set the percentages your contracts give.
- **Public holidays:** one tap fills in the fixed-date holidays and both Easters for the year; add the Bajram days when they are announced.
- **Bonuses and advances** for the month, **approving the month** (the numbers stay even if a clock-in changes later), printing and Excel with IBANs for the bank and the accountant.
- Contributions and income tax stay with the accountant: they change every year, and a wrong figure on a payslip is worse than none.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.20.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.19.0 — several businesses, one owner; tills that warn when offline

**Shqip**

- **Pamja e grupit:** për pronarët me disa biznese. Çdo biznes mban InnKeeper-in dhe të dhënat e veta (arkat, stafin, regjistrimin fiskal); secili mund të ndajë një përmbledhje vetëm për lexim me një çelës sekret (*Cilësimet → Pamja e grupit*). Te InnKeeper-i i pronarit, *Menaxhimi → Pamja e grupit* tregon të gjitha bizneset në një faqe: shitjet sot dhe këtë muaj, paratë e arkëtuara, faturat e hapura, dhomat, kush është në punë, paralajmërimet, dhe totalet. Pa emra mysafirësh ose stafi; funksionon me Tailscale ose adresë publike.
- **Kur humbet lidhja:** nëse një tablet humbet Wi-Fi-n ose kompjuteri i InnKeeper fiket, një mesazh i kuq e thotë qartë dhe prekjet që do të ruanin diçka mbahen, që asgjë të mos ruhet përgjysmë. Largohet vetë kur kthehet lidhja.

**English**

- **Group overview:** for owners of several businesses. Each business keeps its own InnKeeper and data (tills, staff, fiscal registration); each can share a read-only summary with a secret key (*Settings → Group overview*). On the owner's InnKeeper, *Management → Group overview* shows every business on one page: sales today and this month, money received, open bills, rooms, who is at work, warnings, and totals. No guest or staff names; works over Tailscale or a public address.
- **When the connection drops:** if a tablet loses the Wi-Fi or the InnKeeper computer goes off, a red message says so clearly and taps that would save something are held back, so nothing is half-saved. It goes away by itself when the connection is back.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.19.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.18.0 — messages to guests

**Shqip**

- **Mesazhet për mysafirët** (*Cilësimet → Mesazhet për mysafirët*): disa ditë para mbërritjes, çdo mysafir i konfirmuar merr me email informacionin tuaj (si t'ju gjejnë, parkimi, Wi-Fi), orën e hyrjes, adresën dhe butonin e hartës; një ditë pas largimit, një falënderim me linkun tuaj të vlerësimeve (Google Maps, TripAdvisor, Booking.com). Secili dërgohet një herë, në orën që zgjidhni, në shqip ose anglisht sipas mysafirit, me parapamje.
- **WhatsApp me një prekje:** te rezervimi, butoni *WhatsApp* hap bisedën me mesazhin gati — për mysafirët pa email (numrat 069… kthehen automatikisht në +355). Mund ta dërgoni edhe me email me dorë.
- **Rregullim:** *I pritshëm në largim* tani përfshin taksën e turizmit që do të shtohet, që pagesa e plotë të mos ndalojë largimin.
- Në telefon, faqet me dy kolona nuk dalin më jashtë ekranit kur kanë linke të gjata.

**English**

- **Guest messages** (*Settings → Guest messages*): a few days before arrival, every confirmed guest is emailed your arrival information (how to find you, parking, Wi-Fi), the check-in time, your address and a map button; the day after check-out, a thank-you with your review link (Google Maps, TripAdvisor, Booking.com). Each is sent once, at the hour you choose, in Albanian or English to suit the guest, with a preview.
- **One-tap WhatsApp:** on a reservation, the *WhatsApp* button opens the chat with the message ready — for guests without email (069… numbers become +355 automatically). You can also email it by hand.
- **Fix:** *Expected at check-out* now includes the tourist tax that will be added, so paying it in full no longer blocks check-out.
- On phones, two-column pages no longer run off the screen when they contain long links.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.18.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.17.0 — ordering from the table (QR)

**Shqip**

- **Porosia nga tavolina:** çdo tavolinë merr kartën e vet QR (*Pikat & menutë → Menuja → Printo kodet e tavolinave*). Klientët porosisin nga telefoni, me opsione dhe shënim, në shqip ose anglisht; mund edhe të thërrasin kamarierin ose të kërkojnë faturën.
- **Stafi pranon çdo porosi:** te *Porositë nga tavolina* (me numër të kuq, zile dhe ikonë në planin e sallës). *Prano dhe dërgo* e shton në faturën e tavolinës dhe e dërgon direkt në kuzhinë/bar; *Refuzo* me arsye që klienti e sheh në telefon. Asgjë nuk shkon në faturë pa u pranuar.
- **E sigurt:** kufi kërkesash për telefon dhe për tavolinë, vetëm artikujt në dispozicion të asaj pike, kërkesat pa përgjigje skadojnë pas një ore, dhe *Krijo kode të reja* çaktivizon kartat e vjetra.
- Ndizeni për çdo pikë te cilësimet e saj: *Klientët porosisin nga tavolina*.

**English**

- **Ordering from the table:** each table gets its own QR card (*Outlets & menus → Menu → Print table codes*). Guests order from their phone, with options and a note, in Albanian or English; they can also call the waiter or ask for the bill.
- **Staff accept every order:** under *Table orders* (with a red count, a chime and an icon on the floor plan). *Accept and send* puts it on the table's bill and straight to the kitchen/bar; *Decline* with a reason the guest sees on their phone. Nothing reaches a bill without being accepted.
- **Safe:** limits per phone and per table, only that outlet's available items, unanswered requests expire after an hour, and *Make new codes* stops old cards working.
- Turn it on per outlet in its settings: *Guests can order from the table*.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.17.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.16.0 — tourist tax

**Shqip**

- **Taksa e turizmit:** ndizeni te *Cilësimet → Taksa e turizmit* me shumën që vendos bashkia juaj — për mysafir ose për dhomë për natë, me ose pa fëmijët, dhe me një kufi netësh nëse bashkia e ka. Shtohet automatikisht në faturë me çdo natë dhome.
- Nuk është e ardhura juaj: mbetet jashtë shitjeve, TVSH-së dhe faturës fiskale, dhe shfaqet veçmas te mbyllja e ditës dhe raporti mujor.
- **Financa → Taksa e turizmit:** totali i muajit dhe lista e qëndrimeve (mysafiri, kombësia, dhoma, datat, netët), për printim ose Excel. Nga data 1 deri më 5 faqja kryesore ju kujton ta paguani.

**English**

- **Tourist tax:** turn it on in *Settings → Tourist tax* with the amount your municipality sets — per guest or per room per night, with or without children, and with a nights limit if your municipality has one. It is added to the bill automatically with each room night.
- It is not your income: it stays out of sales, VAT and the fiscal invoice, and is shown on its own in the day close and the month report.
- **Finance → Tourist tax:** the month's total and the list of stays (guest, nationality, room, dates, nights), to print or download to Excel. From the 1st to the 5th the home page reminds you to pay it.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.16.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.15.0 — staff clock-in, schedule and employee details

**Shqip**

- **Hyrja dhe dalja e stafit:** butoni *Hyrje / Dalje* poshtë emrit në menu, dhe mënyra *Hyrje / dalje* në ekranin e PIN-it të arkës së përbashkët (shënon orën pa hyrë në aplikacion). Pika e gjelbër tregon kush është në punë.
- **Orari javor:** një rresht për çdo person, turne me ngjyrën e pozicionit, turne që mbarojnë pas mesnate, *Kopjo javën e kaluar*, printim. Secili sheh turnet e veta te *Orët e mia*.
- **Prezenca:** kush është në punë tani; për çdo periudhë ditët, orët e punuara dhe të planifikuara, diferenca, vonesat, mungesat dhe daljet e harruara; korrigjime nga menaxheri me arsye (në regjistrin e aktivitetit); shkarkim në Excel për pagat.
- **Pozicionet dhe të dhënat e punonjësve:** pozicioni, lloji i punësimit, data e fillimit, orët e kontratës, kontakti për emergjenca, numri personal, paga dhe IBAN — vetëm për menaxherët.
- Përmbledhja ditore paralajmëron për këdo që është ende në punë pas 16 orësh. Biznesi shembull ka pozicione dhe orarin e javës.

**English**

- **Staff clock-in and clock-out:** a *Clock in / Clock out* button under each name in the menu, and a *Clock in / out* mode on the shared till's PIN screen (records the time without signing in). A green dot shows who is at work.
- **Weekly schedule:** one row per person, shifts in the position's colour, shifts past midnight, *Copy last week*, printing. Everyone sees their own shifts under *My hours*.
- **Attendance:** who is working now; for any period each person's days, hours worked and planned, the difference, late arrivals, no-shows and forgotten clock-outs; manager corrections with a reason (in the activity log); Excel for payroll.
- **Positions and employee details:** position, employment type, start date, contract hours, emergency contact, personal ID number, pay and IBAN — managers only.
- The owner's daily summary warns about anyone still clocked in after 16 hours. The sample business has positions and this week's schedule.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.15.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.14.1 — sign-in through Cloudflare Tunnel

**Shqip**

- **Rregullim:** hyrja përmes Cloudflare Tunnel (adresa publike) refuzohej me “403” në aplikacionin Windows, sepse serveri i brendshëm e hidhte poshtë shënimin “https” që dërgon tuneli. Tani pranohet vetëm kur vjen nga ky kompjuter. Edhe cookie-t e hyrjes tani janë “Secure” përmes tunelit.
- Test i ri i plotë në një kompjuter të vërtetë Windows: nisja, shkarkimi dhe ndalimi i Cloudflare Tunnel, një tunel i vërtetë publik me hyrje dhe faqe përmes internetit, PIN-i i refuzuar nga jashtë, dhe dërgimi i një kuponi në sistemin provë të tatimeve.

**English**

- **Fix:** signing in through Cloudflare Tunnel (the public address) was refused with “403” in the Windows app, because the built-in server dropped the “https” note the tunnel sends. It is now trusted only when it comes from this computer. Sign-in cookies are now Secure through the tunnel too.
- New full test on a real Windows computer: start-up, downloading and stopping Cloudflare Tunnel, a real public tunnel with sign-in and pages over the internet, the PIN refused from outside, and a receipt sent to the tax authority's test system.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.14.1.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.14.0 — access from outside, month report, minimum stay at reception, opening cash per register

**Shqip**

- **Hyrja nga jashtë** (Cilësimet → Hyrja nga jashtë): adresa për telefonat në Wi-Fi të biznesit; udhëzues për **Tailscale** (falas, privat) që pronari ta hapë InnKeeper nga telefoni kudo pa hapur asgjë në internet, me kod QR; dhe **Cloudflare Tunnel** për adresën publike (rezervimi online, pagesat me kartë): ngjitni tokenin dhe aplikacioni Windows e shkarkon dhe e mban tunelin në punë.
- PIN-et e arkave punojnë vetëm brenda rrjetit të biznesit; nga jashtë kërkohet gjithmonë fjalëkalimi.
- **Raporti mujor** (Financa → Raporti mujor): shitjet sipas departamentit, TVSH sipas normës, paratë sipas mënyrës së pagesës, shpenzimet, fitimi, kontrollet dhe çdo ditë me numërimin e arkës. Printohet ose ruhet si PDF, ose shkarkohet në Excel.
- **Qëndrimi minimal në recepsion:** kur një rezervim është më i shkurtër se minimumi i sezonit, kërkohet “Rezervoje gjithsesi”, dhe shënohet në regjistrin e aktivitetit.
- **Paratë e fillimit për çdo arkë fiskale:** çdo pikë me arkën e vet deklaron kusurin e saj; arka kryesore deklaron pjesën tjetër të numërimit, pa e dyfishuar.
- Paneli i Financës nuk i llogarit më pagesat me kupon dhuratë si para të marra.

**English**

- **Access from outside** (Settings → Access from outside): the address for phones on the business Wi-Fi; a guide to **Tailscale** (free, private) so the owner reaches InnKeeper from their phone anywhere without opening anything to the internet, with a QR code; and **Cloudflare Tunnel** for the public address (online booking, card payments): paste the token and the Windows app downloads it and keeps the tunnel running.
- Till PINs only work inside the business network; from outside the password is always needed.
- **Month report** (Finance → Month report): sales by department, VAT by rate, money by payment method, expenses, profit, checks and every day with its cash count. Print or save as PDF, or download to Excel.
- **Minimum stay at reception:** a booking shorter than the season's minimum needs “Book it anyway”, and it is noted in the activity log.
- **Opening cash per fiscal register:** each outlet with its own register reports its own change; the main register reports the rest of the count, never twice.
- The Finance overview no longer counts gift-voucher payments as money received.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.14.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.13.0 — loyalty cards and gift vouchers

**Shqip**

- **Kartat e besnikërisë:** te Cilësimet → Besnikëria & kuponat dhuratë zgjidhni sa vula japin një artikull falas (p.sh. 9: kafeja e dhjetë falas) dhe shënoni artikujt që japin vulë. Në arkë shkruhet telefoni ose numri i kartës (ose krijohet një kartë e re me emrin dhe telefonin). Kur ka vula të mjaftueshme, *Jep artikullin falas* e bën falas artikullin më të lirë të shënuar. Llogaritë e anuluara i marrin vulat mbrapsht. Faqja *Kartat e besnikërisë* tregon vulat dhe vizitat e secilit.
- **Kuponat dhuratë:** shiten me para në dorë, kartë ose transfertë dhe printohen me kod. Shpenzohen në çdo arkë me ikonën e dhuratës, në një ose disa vizita, deri sa të mbarojë vlera ose të skadojë. Mbyllja e ditës i tregon veçmas kuponat e shitur (para të marra përpara) dhe ato të shpenzuar (pa para atë ditë). Në kuponin fiskal mënyra e pagesës është “SVOUCHER” — konfirmojeni me kontabilistin.

**English**

- **Loyalty cards:** in Settings → Loyalty & gift vouchers, choose how many stamps give a free item (e.g. 9: the tenth coffee is free) and mark the items that earn a stamp. At the till, type the phone or card number (or create a new card with name and phone). With enough stamps, *Give the free item* makes the cheapest marked item free. Voided bills take their stamps back. The *Loyalty cards* page shows everyone's stamps and visits.
- **Gift vouchers:** sold for cash, card or bank transfer and printed with a code. Spent at any till with the gift icon, in one or several visits, until the value is used up or it expires. The day close shows vouchers sold (money received in advance) and vouchers spent (no money that day) separately. On fiscal receipts the payment type is “SVOUCHER” — confirm this with your accountant.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.13.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.12.0 — shared tills with PIN, profit per item, kitchen sound, bills in English

**Shqip**

- **Arkat e përbashkëta me PIN:** te Cilësimet → Arkat e përbashkëta & PIN, shënoni tabletën e barit si arkë të përbashkët. Ajo hapet me emrat e stafit: secili prek emrin dhe shkruan PIN-in (4–6 shifra). *Kyç / ndrysho përdoruesin* ia jep arkën tjetrit, dhe ajo kyçet vetë pas disa minutash. Çdo shitje mbetet në emrin e duhur. PIN-et ruhen të enkriptuara; pesë gabime e kyçin për 15 minuta. Pajisjet e tjera vazhdojnë me fjalëkalim.
- **Fitimi për artikull:** Stoku → Fitimi për artikull tregon koston nga receta, çmimin pa TVSH, marzhin, sasinë e shitur dhe fitimin për çdo artikull; artikujt me marzh të ulët dalin me të kuqe. Shkarkohet në Excel.
- **Zëri i kuzhinës:** ekrani i kuzhinës bie zile dhe ndriçon për çdo porosi të re (tani i ndezur si parazgjedhje), dhe kujton çdo minutë porositë që presin më shumë se 2 minuta. Kamarierët marrin zile dhe shirit të gjelbër kur porosia është gati.
- **Fatura në anglisht:** butoni *EN* pranë *Printo llogarinë* printon llogarinë në anglisht me emrat anglisht të menusë. Kuponi dhe fatura e mysafirit kanë zgjedhjen Shqip / English.
- Ikonat e butonave në faqen e kuponit shfaqen sërish.

**English**

- **Shared tills with a PIN:** in Settings → Shared tills & PINs, mark the bar tablet as a shared till. It opens on the staff names: each person taps their name and types their PIN (4–6 digits). *Lock / switch user* hands the till over, and it locks itself after a few minutes. Every sale stays under the right person. PINs are stored encrypted; five wrong tries lock it for 15 minutes. Other devices keep using passwords.
- **Profit per item:** Stock → Profit per item shows the recipe cost, price without VAT, margin, quantity sold and profit for every item; low-margin items are red. Downloads to Excel.
- **Kitchen sound:** the kitchen screen beeps and flashes on every new order (now on by default) and reminds every minute about orders waiting over 2 minutes. Waiters get a chime and a green banner when an order is ready.
- **Bills in English:** the *EN* button next to *Print bill* prints the bill in English with the English menu names. The receipt and guest invoice pages have a Shqip / English choice.
- The buttons on the receipt page show their icons again.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.12.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.11.1 — language check

**Shqip**

- Çdo ekran u kontrollua në shqip: asnjë tekst i ndërfaqes nuk mbetet në anglisht.
- Biznesi shembull është tani në shqip: Restoranti, Bari, Shërbimi në dhomë, Lavanderia, pjatat (Levrek në skarë, Mëngjes shqiptar…) dhe zonat e tavolinave (Brenda, Tarracë). Emrat anglisht mbeten për menunë anglisht.
- Porositë te furnitorët: kolona “Porosia” shfaqej gabim si “Renditja”; statusi “Pranuar”. Stoku që po mbaron shënohet “Po mbaron”, jo “E ulët”.
- Regjistri i aktivitetit shkruan në shqip “u dërguan artikuj”, mënyrën e pagesës dhe të dhënat shembull. “Paraqitja” e kuponit u bë “Parapamja”.

**English**

- Every screen was checked in Albanian: no interface text is left in English.
- The sample business is now Albanian: Restoranti, Bari, Shërbimi në dhomë, Lavanderia, the dishes and the table zones (Brenda, Tarracë). The English names stay for the English menu.
- Orders to suppliers: the “Order” column showed the word for sort order; the received status and the low-stock badge now use the right words.
- The activity log writes sent items, the payment method and sample data in the user's language. The receipt “Preview” button uses the right Albanian word.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.11.1.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.11.0 — Excel files, daily summary, orders to suppliers, sample data

**Shqip**

- **Skedarë të vërtetë Excel (.xlsx):** importi i menusë, stokut dhe mysafirëve pranon drejtpërdrejt skedarin .xlsx (s'ka më “Save as CSV”). Shablloni shkarkohet si Excel, me një fletë të dytë që shpjegon çdo kolonë me shembull. Libri i llogarive, raporti i shitjeve, lista e stokut dhe regjistri i mysafirëve shkarkohen në Excel me shumat si numra, datat si data dhe filtër në çdo kolonë. CSV mbetet për kush e do.
- **Përmbledhja ditore për pronarin:** te Cilësimet → Email, shkruani adresat dhe orën. Çdo mëngjes vjen një email i shkurtër: shitjet krahasuar me një javë më parë, paratë sipas mënyrës, numërimi i arkës dhe diferenca, zbritjet, anulimet, turnet me diferencë, më të shiturat, dhomat dhe paralajmërimet (stok që mbaron, kupona pa fiskalizuar, kopje që nuk punojnë). Dërgohet edhe pas mbylljes së ditës. Për lokalet e natës, nata e së shtunës vjen të dielën në mëngjes.
- **Porositë te furnitorët:** Stoku → Porositë → *Porosit atë që po mbaron* përgatit një porosi për çdo furnitor. Dërgojeni me WhatsApp (hapet me porosinë të shkruar), me email, printojeni ose kopjojeni. Kur vjen malli, *Erdhi: prano* hap furnizimin të plotësuar dhe stoku rritet.
- **Provojeni me të dhëna shembull:** në ekranin e parë të konfigurimit, një hotel, restorant, bar dhe spa shembull për të parë gjithçka në punë. Një shirit i verdhë e tregon; *Fillo me biznesin tim* i heq të gjitha dhe nis konfigurimin. Fiskalizimi nuk aktivizohet dot me të dhëna shembull.
- Në telefon, rreshtat e furnizimeve dhe porosive shfaqen si karta, pa u ngushtuar.

**English**

- **Real Excel files (.xlsx):** importing the menu, stock and guests takes the .xlsx file directly (no more “Save as CSV”). The template downloads as Excel, with a second sheet explaining each column with an example. The ledger, sales report, stock list and guest register download to Excel with money as numbers, dates as dates and a filter on every column. CSV is still there for anyone who wants it.
- **Daily summary for the owner:** in Settings → Email, type the addresses and the hour. Every morning a short email arrives: sales compared with a week ago, money by method, the cash count and any difference, discounts, voids, shifts with a difference, best sellers, rooms, and warnings (stock running low, receipts not fiscalized, copies not working). It is also sent after the day close. For late-night venues, Saturday night arrives on Sunday morning.
- **Orders to suppliers:** Stock → Orders → *Order what is running low* prepares one order per supplier. Send it by WhatsApp (opens with the order written), email, print or copy it. When the goods arrive, *It arrived: receive* opens the delivery already filled in and the stock goes up.
- **Try it with sample data:** on the first setup screen, a sample hotel, restaurant, bar and spa to see everything working. A yellow banner shows it; *Start with my own business* removes it all and starts the setup. Fiscalization can't be switched on while sample data is loaded.
- On phones, delivery and order lines show as cards instead of a squeezed table.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.11.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.10.0 — table bookings, club tables and entrance sales

**Shqip**

- **Rezervimet e tavolinave:** te ekrani i tavolinave → *Rezervimet*. Mjaftojnë emri, dita, ora dhe numri i personave; telefoni, tavolina dhe shënimi nuk janë të detyrueshëm. Tavolina e rezervuar shfaqet në planimetri “20:00 · Emri (6)” tre orë përpara. Kur vijnë, *Uli* hap llogarinë në tavolinë me emrin dhe numrin e personave. Dy rezervime nuk mbivendosen dot në të njëjtën tavolinë. Në telefon, çdo rezervim është një kartë me butonat poshtë.
- **Tavolinat e klubit me shpenzim minimal:** shkruani minimumin te rezervimi; arka tregon sa mungon ende dhe *Shto diferencën* e shton si një rresht.
- **Shitja me një prekje (hyrja, biletat, marrja me vete):** shënoni *Shitje me një prekje* te pika. Ekrani shfaq butona të mëdhenj; zgjidhni një herë para në dorë ose kartë, dhe çdo prekje shet dhe merr pagesën menjëherë (fiskalizohet kur fiskalizimi është aktiv). Çdo buton numëron shitjet e sontme.
- Për lokalet e natës, data e rezervimit është data e mbrëmjes: një rezervim në 01:00 të së shtunës natën shënohet të shtunën.

**English**

- **Table bookings:** on the tables screen → *Bookings*. Name, day, time and number of people are enough; phone, table and a note are optional. A booked table shows “20:00 · Name (6)” on the floor plan from three hours before. When they arrive, *Seat* opens the bill on the table with their name and party size. Two bookings can't overlap on the same table. On a phone each booking is a card with its buttons underneath.
- **Club tables with a minimum spend:** type the minimum on the booking; the till shows how much is still missing and *Add the difference* adds it as one line.
- **One-tap sale (entrance, tickets, takeaway):** tick *One-tap sale* on the outlet. Its screen shows big buttons; choose cash or card once, and every tap sells and takes the payment at once (fiscalized when that is on). Each button counts tonight's sales.
- For late-night venues the booking date is the evening's date: a booking at 01:00 on Saturday night goes on Saturday.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.10.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.9.0 — options, happy hour, customer accounts, shifts and tips

**Shqip**

- **Opsionet e artikujve:** madhësia, sheqeri, shtesat… (Pikat & menutë → Opsionet). Në arkë, artikulli hap një listë të shkurtër zgjedhjesh; çmimi ndryshon vetë dhe zgjedhjet printohen në biletën e kuzhinës, në kupon dhe në kuponin fiskal.
- **Happy hour dhe çmimet e natës:** çmime sipas orarit dhe ditëve, për pika ose kategori të caktuara (p.sh. −20% për pijet 17–19, ose +15% pas orës 23 në klub). Arka tregon çmimin e vjetër të vizatuar dhe të riun.
- **Llogaritë e klientëve (borxhi):** klientët e rregullt marrin tani dhe paguajnë më vonë. Në arkë “Borxh”, në faqen e klientit pasqyra me bilancin, pagesat dhe printimi. Kufi kredie, borxh i mëparshëm nga fletorja. Shitja fiskalizohet menjëherë.
- **Turnet e stafit:** çdo kamarier fillon turnin me paratë e fillimit; në fund InnKeeper tregon sa para duhet të dorëzojë dhe diferencën. Menaxheri i sheh te Financa → Turnet.
- **Bakshishet:** për kartë shkruhet bakshishi, për para në dorë “Klienti e lë si bakshish”. Nuk llogariten si të ardhura; bakshishet me kartë zbriten nga paratë e arkës në mbylljen e ditës.
- Mbyllja e ditës tregon shitjet me borxh, pagesat e borxheve dhe bakshishet. Opsionet dhe happy hour përfshihen në eksportin e cilësimeve.

**English**

- **Item options:** size, sugar, extras… (Outlets & menus → Options). On the till the item opens a short list of choices; the price changes by itself and the choices are printed on the kitchen ticket, the receipt and the fiscal receipt.
- **Happy hour and late-night prices:** prices by time and day, for chosen outlets or categories (e.g. −20% on drinks 17–19, or +15% after 23:00 in a club). The till shows the old price struck through and the new one.
- **Customer accounts (tabs):** regulars take now and pay later. “Account” on the till; the customer's page shows the statement with the balance, payments and printing. Credit limits, and what they owed from before (the notebook). The sale is fiscalized straight away.
- **Staff shifts:** each waiter starts a shift with the cash they start with; at the end InnKeeper shows how much cash to hand in and the difference. Managers see them under Finance → Shifts.
- **Tips:** type the tip for a card payment, or tick “Guest leaves it as a tip” for cash. Tips aren't revenue; card tips come off the cash expected in the day close.
- The day close shows sales on account, account payments and tips. Options and happy hour are part of the settings export.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.9.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.8.0 — phones for waiters and staff

**Shqip**

- **Arka në telefon:** në telefon, porosia ka dy ekrane — Menuja dhe Llogaria — me një shirit poshtë që tregon numrin e artikujve, totalin dhe butonin Dërgo. Prekja e një artikulli e shton menjëherë pa ringarkuar faqen: menuja mbetet aty ku ishit dhe një mesazh i shkurtër konfirmon artikullin. Kategoritë rrëshqasin në një rresht, butonat − / + janë më të mëdhenj, ndryshimi i tavolinës dhe printimi janë te “Më shumë”.
- Edhe në kompjuter dhe tablet, shtimi i artikujve dhe − / + nuk e ringarkojnë më faqen.
- **Si aplikacion:** InnKeeper mund të shtohet në ekranin kryesor të telefonit (Add to Home screen) me ikonën e vet.
- **Pastrimi** në telefon hapet te dhomat që duhen pastruar.
- Rregullime: faqja e porosisë dhe kopjet rezervë nuk zmadhoheshin më gjerë se ekrani i telefonit.
- Udhëzuesi: seksion i ri “Përdorimi me telefon”.

**English**

- **Till on phones:** on a phone an order has two screens — Menu and Bill — with a bar at the bottom showing the item count, the total and a Send button. Tapping an item adds it straight away without reloading: the menu stays where you were and a short message confirms the item. Categories scroll in one line, − / + buttons are bigger, moving the table and printing are under “More”.
- On computers and tablets too, adding items and − / + no longer reload the page.
- **Like an app:** InnKeeper can be added to the phone's home screen (Add to Home screen) with its own icon.
- **Housekeeping** on a phone opens on the rooms that need cleaning.
- Fixes: the order page and the backup page no longer became wider than a phone screen.
- Guide: new section “Using a phone”.

### Install or update on Windows
1. In InnKeeper 2.7.0 or newer: **Settings → Updates → Update now**. Otherwise download **InnKeeper-Setup-2.8.0.exe** below and run it. Updating keeps all your data; a backup is made first.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.7.0 — automatic copies and one-click updates

**Shqip**

- **Kopje automatike në një vend tjetër:** te Cilësimet → Kopje rezervë & rikthim zgjidhni një USB ose një dosje të OneDrive / Google Drive / Dropbox. InnKeeper shkruan atje një kopje të plotë sipas orarit (çdo 15 minuta deri një herë në ditë), e lexon sërish për ta kontrolluar dhe mban kopjet e dy ditëve të fundit, një në ditë për dy muaj dhe një në muaj më pas. Me fjalëkalim, kopjet enkriptohen. Kur InnKeeper ndalet bëhet edhe një kopje e fundit. Nëse kopjimi ndalon (p.sh. USB e hequr), paneli shfaq paralajmërim të kuq. Rikthimi i një kopjeje bëhet me një buton.
- **Përditëso tani:** Cilësimet → Përditësimet shkarkon versionin e ri nga GitHub, kontrollon kodin SHA-256, ruan një kopje rezervë dhe e instalon; InnKeeper hapet sërish vetë.
- **Udhëzues për “Windows protected your PC”:** si ta instaloni sigurt (More info → Run anyway), paralajmërimet e shfletuesit dhe antivirusit, kontrolli i skedarit. Te Ndihma dhe në [docs/windows-install.md](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md).
- Paralajmërimet në panel me buton nuk e çojnë më butonin në rresht të ri.

**English**

- **Automatic copies to another place:** in Settings → Backup & restore choose a USB drive or a OneDrive / Google Drive / Dropbox folder. InnKeeper writes a full copy there on a schedule (every 15 minutes to once a day), reads it back to check it, and keeps every copy from the last two days, one per day for two months and one per month after that. With a password the copies are encrypted. A last copy is made when InnKeeper stops. If copying stops working (e.g. the USB drive is out), the dashboard shows a red warning. Restoring a copy is one button.
- **Update now:** Settings → Updates downloads the new version from GitHub, checks its SHA-256, saves a backup and installs it; InnKeeper reopens by itself.
- **Guide for “Windows protected your PC”:** how to install safely (More info → Run anyway), browser and antivirus warnings, checking the file. In Help and in [docs/windows-install.md](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md).
- Dashboard alerts with a button no longer push the button onto a new line.

### Install or update on Windows
1. Download **InnKeeper-Setup-2.7.0.exe** below and run it. Updating keeps all your data; a copy of the database is made first. From this version on, later updates can be installed from inside InnKeeper.
2. Windows may show "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway** ([step-by-step guide](https://github.com/UncleKraken/InnKeeper/blob/master/docs/windows-install.md)).

## 2.6.0 — tax registration options

**Shqip**

- **Regjistrimi tatimor** (në konfigurim dhe te Cilësimet → Të dhënat e biznesit), me tri zgjedhje:
  - **I regjistruar, me TVSH:** si deri tani.
  - **I regjistruar, pa TVSH:** për bizneset e vogla. Pa rreshta TVSH në kupona, fatura dhe menu; NIPT-i dhe fiskalizimi mbeten.
  - **I paregjistruar:** për shoqata, lokale jashtë Shqipërisë, përdorim të brendshëm ose provë. Asnjë NIPT, TVSH apo fiskalizim, regjistri i mysafirëve fshihet, faturat e mysafirëve quhen kupona dhe çdo kupon shkruan “Kupon i brendshëm”.
- Arka, dhomat, stoku, raportet, kopjet rezervë dhe mbyllja e ditës punojnë njësoj në të tria rastet.
- “Emri i hotelit” tani quhet “Emri i biznesit”. Në kupon TVSH-ja shfaqet si “20%”, jo “20.00%”.

**English**

- **Tax registration** (in the setup wizard and in Settings → Business details), with three options:
  - **Registered, with VAT:** as before.
  - **Registered, without VAT:** for small businesses. No VAT lines on receipts, invoices and menus; the NIPT and fiscalization stay available.
  - **Not registered:** for associations, places outside Albania, internal use or trying the app. No NIPT, VAT or fiscalization anywhere, the guest register is hidden, guest bills are called receipts and every receipt says “Internal receipt”.
- The till, rooms, stock, reports, backups and day close work the same in all three.
- “Hotel name” is now “Business name”. The printed receipt shows VAT as “20%”, not “20.00%”.

Existing installs keep working as before: with a VAT rate they become “Registered, with VAT”, without one “Registered, without VAT”.

### Install or update on Windows
1. Download **InnKeeper-Setup-2.6.0.exe** below and run it. Updating keeps all your data; a copy of the database is made first.
2. Windows may show "Windows protected your PC" because the installer is not yet code-signed. Click **More info → Run anyway**.

## 2.5.2 — night bars and clubs

**Shqip**

- **Dita e punës mbyllet në:** për lokalet që punojnë pas mesnate (p.sh. 04:00). Shitjet, pagesat, shpenzimet dhe stoku deri në atë orë llogariten në natën që u përkasin, që e gjithë nata të jetë në një mbyllje dite; mbyllja e ditës e hapur në 02:00 tregon atë natë. Netët e dhomave dhe kuponat fiskalë mbajnë datën e kalendarit. Te Cilësimet → Të dhënat e biznesit.
- **Lloj i ri biznesi:** “Bar nate, klub ose lounge” në konfigurim, me barin dhe mbylljen e ditës në 05:00 të gatshme.

**English**

- **Business day ends at:** for places open after midnight (e.g. 04:00). Sales, payments, expenses and stock until that hour count on the night they belong to, so the whole night is in one day close; the day close opened at 02:00 shows that night. Room nights and fiscal receipts keep the calendar date. In Settings → Business details.
- **New business type:** “Night bar, club or lounge” in the setup wizard, with a bar and a 05:00 day end ready.

### Install or update on Windows
1. Download **InnKeeper-Setup-2.5.2.exe** below and run it. Updating keeps all your data; a copy of the database is made first.
2. Windows may show "Windows protected your PC" because the installer is not yet code-signed. Click **More info → Run anyway**.

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
