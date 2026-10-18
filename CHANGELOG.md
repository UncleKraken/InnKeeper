# Changelog

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
