# PLAN.md

## Ziel

Eine stabile, sichere und austauschbare Plymouth-Boot-Splash-Infrastruktur für die bestehende NixOS-Konfiguration bauen.

Der Zielablauf ist:

```text
systemd-boot
  -> Kernel + systemd-initrd
  -> Plymouth startet sofort
  -> LUKS-Passwort wird über den normalen Plymouth/systemd-Ask-Password-Pfad abgefragt
  -> Unlock erfolgreich
  -> aktive Bootanimation läuft ohne schwarzen Zwischenbildschirm weiter
  -> finaler READY-/Idle-Zustand bleibt sichtbar
  -> Noctalia Greeter ist bereit
  -> sauberer Handoff von Plymouth zu greetd/Noctalia
```

Die erste eigene Animation orientiert sich visuell an der vorhandenen ZOOT-/Arknights-Terminalanimation. Das Bash-Script ist Referenz, aber keine zwingende Runtime-Abhängigkeit.

Zusätzlich entsteht eine generische Theme-Infrastruktur. Das System darf nicht fest auf ZOOT verdrahtet sein.

## Anforderungen

### Kernanforderungen

- Plymouth ist die durchgehende Boot-UI von initrd/LUKS bis zum Greeter.
- Kein eigener Code verarbeitet oder speichert das LUKS-Passwort.
- Keine eigenen Cryptsetup-Wrapper.
- `boot.plymouth.showDelay = 0`.
- Nach erfolgreichem LUKS-Unlock soll die sichtbare Animation ohne Neustart eines zweiten Renderers weiterlaufen.
- Die Hauptanimation läuft vollständig durch.
- Danach bleibt ein dezenter READY-/Idle-Zustand aktiv, bis Noctalia übernehmen kann.
- Der normale Systemstart läuft parallel zur Animation.
- Schwarze Zwischenframes sollen so weit wie technisch möglich vermieden werden.
- Der letzte Plymouth-Frame soll beim Handoff nach Möglichkeit erhalten bleiben, bis Noctalia zeichnet.
- Beide Hosts `nyx` und `aether` müssen unterstützt werden.
- Mango, Niri und Hyprland bleiben unabhängig von der Splash-Architektur.
- Rollback über NixOS-Generationen muss jederzeit möglich bleiben.

### Austauschbare Themes

Die NixOS-Konfiguration definiert:

1. einen sicheren Default-Theme-Namen,
2. eine Allowlist von gebündelten Themes,
3. die Plymouth-Basisintegration.

Beispielhafte Ziel-API:

```nix
bootSplash = {
  enable = true;
  defaultTheme = "zoot";

  themes = {
    zoot = ./themes/plymouth/zoot;
    minimal = ./themes/plymouth/minimal;
  };
};
```

Der genaue Nix-Optionsname kann während der Implementierung leicht angepasst werden, wenn dadurch die Integration sauberer wird.

### Runtime-Theme-Wechsel ohne NixOS-Rebuild

Der Benutzer soll zwischen bereits gebündelten und geprüften Themes wechseln können, ohne `nixos-rebuild` auszuführen.

Geplante CLI:

```text
plmf theme current
plmf theme list
plmf theme search <text>
sudo plmf theme set <name>
sudo plmf theme reset
plmf theme test <name>
```

Optional dürfen kurze Aliase ergänzt werden, solange die klare Unterbefehl-Struktur erhalten bleibt.

#### Wichtiges Architekturprinzip

Ein Theme, das bereits im initrd-Theme-Bundle enthalten ist, kann ohne Rebuild ausgewählt werden.

Ein komplett neues Theme, das noch nicht gebündelt ist, benötigt einmalig einen NixOS-Rebuild, weil Theme-Dateien und benötigte Plymouth-Plugins bereits vor dem LUKS-Unlock verfügbar sein müssen.

Das ist bewusst so gewählt. Ein beliebiges Theme darf nicht zur Laufzeit aus dem Internet in die initrd eingeschleust werden.

## Bestehende Config

Die vorhandene Config bringt bereits gute Voraussetzungen mit:

- `systemd-boot` ist aktiviert.
- `boot.loader.efi.canTouchEfiVariables = true` ist vorhanden.
- `quiet` ist gesetzt.
- `loglevel=3` ist gesetzt.
- `rd.systemd.show_status=false` ist gesetzt.
- `systemd.show_status=false` ist gesetzt.
- `boot.consoleLogLevel = 0` ist gesetzt.
- Noctalia Greeter wird deklarativ eingebunden.
- Noctalia aktiviert greetd.
- greetd läuft im gepinnten NixOS auf `tty1`.
- NixOS besitzt bereits eine native Plymouth-Integration für initrd, systemd Ask Password und Plymouth-Service-Handoff.

Die bestehende Silent-Boot-Konfiguration soll nicht unnötig neu erfunden werden.

## Architekturansatz 1: deklarativer Theme-Wechsel nur über NixOS-Rebuild

### Tech-Stack

- NixOS
- Plymouth
- systemd initrd
- Nix-Derivations
- greetd
- Noctalia Greeter

### Datenfluss

```text
configuration
  -> bootSplash.defaultTheme
  -> nixos-rebuild
  -> initrd enthält genau das gewählte Theme
  -> nächster Boot verwendet dieses Theme
```

### Vorteile

- maximal simpel
- vollständig deklarativ
- sehr geringe Sonderlogik
- sehr leicht zu debuggen
- klassische NixOS-Arbeitsweise

### Nachteile

- jeder Theme-Wechsel benötigt einen Rebuild
- langsamer und unpraktischer für häufiges Ausprobieren
- erfüllt den gewünschten schnellen `plmf theme set` Workflow nicht gut

### Komplexität

Niedrig

## Architekturansatz 2: Theme-Bundle in initrd plus persistenter Runtime-Selector

### Tech-Stack

- NixOS
- systemd initrd
- Plymouth
- systemd-ask-password-plymouth
- Nix-Derivations
- kleines `plmf` CLI
- persistenter Selector auf der EFI-Systempartition
- greetd
- Noctalia Greeter
- QEMU/NixOS-VM für Theme-Tests

### Grundidee

Alle explizit erlaubten Themes werden beim NixOS-Build in ein gemeinsames initrd-Theme-Bundle gepackt.

Zusätzlich gibt es einen winzigen persistenten Selector außerhalb des verschlüsselten Root-Dateisystems.

Beispiel:

```text
/boot/EFI/PLMF/theme
```

Der Inhalt besteht ausschließlich aus einem validierten Theme-Namen, zum Beispiel:

```text
zoot
```

Dieser Wert ist kein Secret.

Ein sehr früher initrd-Service liest den Selector vor dem Start von Plymouth und wählt nur dann ein Theme daraus, wenn der Name in der beim Build erzeugten Allowlist existiert.

Ist der Selector nicht vorhanden, unlesbar oder ungültig, wird immer `bootSplash.defaultTheme` verwendet.

### Warum der Selector außerhalb des verschlüsselten Root-Dateisystems liegt

Plymouth muss das Theme bereits für die LUKS-Passwortphase kennen.

Ein Selector unter `/var/lib`, `/etc` oder im Home-Verzeichnis wäre vor der Root-Entschlüsselung nicht lesbar.

Die EFI-Systempartition ist dagegen schon vor dem Root-Unlock erreichbar und enthält keine vertraulichen Theme-Daten.

### Datenfluss

```text
NixOS Build
  -> prüft Theme-Allowlist
  -> baut alle erlaubten Themes
  -> kopiert Themes + benötigte Plymouth-Plugins in initrd
  -> erzeugt Default-Theme + Allowlist

Boot
  -> initrd
  -> PLMF selector service
       -> liest /boot/EFI/PLMF/theme über ein read-only gemountetes ESP
       -> validiert exakten Namen gegen Build-Allowlist
       -> ungültig/missing -> Default-Theme
       -> gültig -> Theme auswählen
  -> plymouth-start
  -> LUKS Prompt
  -> Animation
  -> READY Hold
  -> Greeter Handoff
```

### Persistenz bei `nixos-rebuild`

Der Runtime-Selector wird absichtlich nicht von der normalen deklarativen Konfiguration überschrieben.

Damit gilt:

```text
bootSplash.defaultTheme = "zoot"
```

nur als Fallback.

Wenn der Benutzer später ausführt:

```text
sudo plmf theme set minimal
```

bleibt `minimal` auch nach einem normalen `nixos-rebuild switch` aktiv, solange das Theme weiterhin in der Allowlist enthalten ist.

Nur folgende Aktionen ändern den Runtime-Selector:

```text
sudo plmf theme set <name>
sudo plmf theme reset
```

`reset` löscht den Runtime-Override. Beim nächsten Boot greift wieder `bootSplash.defaultTheme`.

Wenn ein ausgewähltes Theme nach einem späteren Config-Update aus der Allowlist entfernt wird, fällt der Boot automatisch auf den Default zurück. Der Boot darf daran nicht scheitern.

### CLI-Verhalten

#### `plmf theme current`

Zeigt mindestens:

```text
Runtime override: minimal
Configured default: zoot
Effective next boot theme: minimal
```

#### `plmf theme list`

Listet nur Themes auf, die aktuell gebündelt und für den nächsten Boot sicher verfügbar sind.

#### `plmf theme search <text>`

Sucht lokal in der installierten Theme-Allowlist und den Theme-Metadaten.

Version 1 führt dabei keine Internetsuche aus.

Das verhindert, dass ein normaler Theme-Suchbefehl unkontrollierten Fremdcode in den Bootpfad bringt.

#### `sudo plmf theme set <name>`

- prüft, ob `<name>` exakt in der Allowlist existiert
- schreibt atomar nur diesen Namen in den Selector
- verändert keine Nix-Dateien
- führt keinen Rebuild aus
- zeigt das effektive Theme für den nächsten Boot an

#### `sudo plmf theme reset`

- entfernt den Runtime-Selector atomar
- Default aus NixOS wird wieder wirksam

#### `plmf theme test <name>`

Startet keinen echten Host-Reboot.

Stattdessen wird die dedizierte NixOS/QEMU-Test-VM mit dem gewünschten Theme gebaut beziehungsweise gestartet.

Damit können visuelle Iterationen durchgeführt werden, ohne den echten Rechner ständig neu zu booten.

### Sicherheit des Selectors

Der Selector darf niemals als Pfad interpretiert werden.

Nicht erlaubt:

```text
../../irgendwas
/nix/store/...
https://...
```

Nur Namen aus einer beim Build erzeugten Allowlist sind gültig.

Der initrd-Service macht sinngemäß:

```text
selected = read selector
if selected in allowedThemes:
    use selected
else:
    use configuredDefault
```

Keine Shell-Auswertung des Inhalts.

Kein `eval`.

Keine dynamischen Downloads.

Keine dynamischen `.so`-Pfade aus dem Selector.

### Theme-Bundle und Plugins

NixOS kopiert standardmäßig nur das konfigurierte Plymouth-Theme und dessen benötigte Teile in die initrd.

Für den Runtime-Switch muss das eigene Modul deshalb bewusst ein Bundle aus allen erlaubten Themes erzeugen.

Zusätzlich müssen alle Plymouth-Plugin-Module enthalten sein, die von diesen Themes benötigt werden.

Version 1 soll bevorzugt folgende Theme-Typen unterstützen:

- Plymouth Script Plugin
- Standard-Plymouth-Plugins aus dem gepinnten Nixpkgs-Paket
- statische Bilder
- Fonts

Fremde native Plugin-Binaries aus zufälligen Theme-Repositories werden nicht automatisch erlaubt.

### Vorteile

- Theme-Wechsel zwischen installierten Themes ohne NixOS-Rebuild
- Runtime-Auswahl bleibt über Rebuilds erhalten
- sauberer deklarativer Default bleibt bestehen
- Theme-Dateien sind trotzdem deterministisch über Nix gebaut
- LUKS-Prompt kann bereits das gewählte Theme benutzen
- keine Internetabhängigkeit im Boot
- schneller Workflow für Theme-Wechsel
- gute Trennung zwischen "Theme installieren" und "Theme auswählen"
- sicherer Fallback auf Default
- spätere Erweiterung des Theme-Katalogs möglich

### Nachteile

- etwas mehr initrd-Logik
- initrd wird mit mehreren Themes größer
- ESP muss für den Selector sehr früh kurz read-only lesbar gemacht werden
- Plugin-Bundle muss sauber validiert werden
- echter Multi-GPU-Handoff muss auf `aether` getestet werden

### Komplexität

Mittel

## Empfehlung

**Ansatz 2 ist der Zielansatz für diese Feature-Branch.**

Er erfüllt die neue Anforderung besser, ohne die Sicherheitsvorteile von NixOS aufzugeben.

Die wichtige Trennung lautet:

```text
Neues Theme hinzufügen
  -> deklarativ in Nix aufnehmen
  -> prüfen
  -> rebuild

Bereits installiertes Theme wechseln
  -> sudo plmf theme set <name>
  -> kein rebuild
```

Damit wird die Config nicht bei jedem Theme-Wechsel umgeschrieben.

Gleichzeitig bleibt die Config die einzige Quelle dafür, welche Themes überhaupt vertrauenswürdig genug sind, in der initrd zu landen.

## ZOOT Theme

Das erste eigene Theme ist `zoot`.

Die vorhandene Terminalanimation dient als Referenz für:

- Reihenfolge
- Text
- Timing
- ZOOT-Logo
- Initialisierungssequenz
- `WELCOME, DOCTOR`
- finalen READY-Zustand

Die Plymouth-Version soll nicht als Fullscreen-Video umgesetzt werden.

Elemente werden separat und responsiv positioniert:

- Hintergrund
- Text
- Linien
- Logo
- Fortschrittsanzeigen
- HUD-Panels

Damit kann das Layout auf unterschiedliche Seitenverhältnisse reagieren.

### Zustände

```text
EARLY_SPLASH
  -> PASSWORD
  -> ZOOT_INIT
  -> ZOOT_WELCOME
  -> READY_HOLD
  -> HANDOFF
```

### READY_HOLD

Der finale Bildschirm bleibt aktiv, bis der Greeter übernehmen kann.

Subtile Animationen:

- `READY` pulsiert langsam
- gelegentliches leichtes Logo-Flicker
- optionale Scanlinie
- kleine Statusbewegungen

Keine hektische Daueranimation.

## Greeter-Handoff

Noctalia läuft über greetd.

Die Implementierung soll zuerst den normalen NixOS/Plymouth-Handoff verwenden.

Ziel:

```text
READY_HOLD
  -> greetd/Noctalia ist startbereit
  -> Plymouth beendet sich mit möglichst erhaltenem Splash
  -> Noctalia zeichnet seinen ersten Frame
```

Wenn dabei ein schwarzer Zwischenframe sichtbar ist, wird als erste Optimierung ein `retain-splash`-basierter Handoff geprüft.

Keine komplexe eigene DRM-Übergabelogik bauen, solange Standard-Plymouth das Problem sauber lösen kann.

## Sicherheit

### LUKS

Das Theme verarbeitet das Passwort nicht selbst.

Pfad bleibt:

```text
Plymouth UI
  -> systemd ask-password
  -> systemd-cryptsetup
  -> LUKS
```

### Initrd

Keine Theme-Netzwerkzugriffe.

Keine Downloader.

Keine User-Home-Dateien.

Keine Secrets.

Keine fremden Installer-Shellscripts.

### Externe Themes

Externe Themes dürfen später unterstützt werden, aber nur über einen geprüften Nix-Paketpfad.

Beispiel:

```text
Git URL + feste Revision + Hash
  -> Review
  -> Nix Derivation
  -> Theme-Allowlist
  -> Systembuild
  -> danach per plmf auswählbar
```

Nicht erlaubt:

```text
curl ... | sh
```

oder ein `plmf theme set`, das beliebige URLs akzeptiert.

### Fail-Safe

- ungültiger Selector -> Default-Theme
- fehlendes Selector-File -> Default-Theme
- fehlendes Runtime-Theme -> Default-Theme
- Theme-Fehler darf Boot nicht dauerhaft blockieren
- Recovery-Pfad und Bootlogs müssen erreichbar bleiben
- Timeout/Fallback für hängende Animation prüfen

## Kosten und Skalierbarkeit

### Laufende Kosten

Keine.

### Speicher

Mehrere gebündelte Themes vergrößern die initrd.

Deshalb:

- keine unnötigen Videos
- keine riesigen Frame-Sequenzen
- Assets optimieren
- Theme-Anzahl in der Allowlist bewusst halten

### Hosts

Das Modul wird in `commonModules` integriert.

Host-spezifische Ausnahmen nur dann, wenn reale Tests zeigen, dass AMD und Intel/NVIDIA unterschiedlich behandelt werden müssen.

## Dateistruktur

Geplante Struktur:

```text
nix-config/
├── PLAN.md
├── flake.nix
├── modules/
│   └── nixos/
│       ├── base.nix
│       ├── boot-splash.nix
│       ├── greeter.nix
│       └── ...
├── themes/
│   └── plymouth/
│       ├── zoot/
│       │   ├── default.nix
│       │   ├── zoot.plymouth
│       │   ├── zoot.script
│       │   └── assets/
│       └── minimal/
│           ├── default.nix
│           └── ...
├── scripts/
│   └── plmf.sh
└── tests/
    └── boot-splash-vm.nix
```

## Erste 3 Dateien

### 1. `modules/nixos/boot-splash.nix`

Generische Splash-Infrastruktur.

Enthält:

- Optionen `enable`, `defaultTheme`, `themes`
- Plymouth-Aktivierung
- `showDelay = 0`
- Theme-Bundle
- Plugin-Bundle
- initrd-Selector-Service
- Default-Fallback
- ESP-Leseintegration
- greetd/Plymouth-Handoff
- Installation des `plmf` CLI

ZOOT-spezifische Darstellung gehört nicht hier hinein.

### 2. `scripts/plmf.sh`

Benutzer-CLI.

Version 1:

```text
plmf theme current
plmf theme list
plmf theme search <text>
plmf theme test <name>
sudo plmf theme set <name>
sudo plmf theme reset
```

Anforderungen:

- klare Fehlermeldungen
- keine Nix-Dateien ändern
- keine Rebuilds bei `set`/`reset`
- atomare Selector-Schreiboperation
- exakte Allowlist-Validierung
- kein Internetzugriff

### 3. `themes/plymouth/zoot/default.nix`

Baut das erste eigene Theme deterministisch als Nix-Paket.

Danach folgen `zoot.plymouth`, `zoot.script` und Assets.

## Teststrategie

### Kein ständiger echter Reboot

Die Entwicklungs- und Theme-Testschleife soll über QEMU laufen.

`plmf theme test <name>` ist dafür der bevorzugte Einstiegspunkt.

### Stufe 1: statische Checks

- `nix flake check`
- Nix-Evaluation
- Shellcheck beziehungsweise Bash-Syntaxcheck für `plmf`
- Theme-Paket prüfen
- Allowlist prüfen
- initrd bauen

### Stufe 2: QEMU-Test

Prüfen:

- Plymouth startet
- Default-Theme funktioniert
- Runtime-Selector wird gelesen
- ungültiger Selector fällt zurück
- LUKS-Prompt wird dargestellt
- erfolgreicher Unlock führt in Animation
- READY_HOLD bleibt aktiv
- Greeter-Handoff funktioniert

### Stufe 3: Theme-Wechsel in VM

```text
set zoot
reboot VM
-> zoot

set minimal
reboot VM
-> minimal

rebuild ohne Selector-Änderung
reboot VM
-> minimal bleibt

reset
reboot VM
-> Default aus Nix
```

### Stufe 4: Auflösungen

Mindestens:

- 1920x1080
- 2560x1440
- 3440x1440

### Stufe 5: `nyx`

Erst nach stabiler VM.

Prüfen:

- LUKS
- AMD KMS
- Unlock -> Animation
- kein störender schwarzer Frame
- Theme-Selector-Persistenz
- Noctalia
- Rollback

### Stufe 6: `aether`

Zusätzlich prüfen:

- Intel iGPU
- NVIDIA PRIME
- Laptop-Panel
- externer Monitor, falls verfügbar

## Umsetzungsschritte

1. Feature ausschließlich auf Branch `feature/plymouth-boot-splash-beta` entwickeln.
2. `main` nicht direkt verändern.
3. Baseline-Build der Branch ausführen.
4. `boot-splash.nix` mit minimalen Optionen anlegen.
5. Plymouth zunächst mit vorhandenem Standardtheme aktivieren.
6. QEMU-Test-VM anlegen.
7. LUKS/Plymouth/Noctalia-Basispfad in VM validieren.
8. Theme-Bundle für mehrere erlaubte Themes implementieren.
9. Build-Allowlist generieren.
10. ESP-Pfad aus der bestehenden NixOS-Konfiguration ableiten, nicht hart auf eine UUID setzen.
11. frühen initrd-Selector-Service implementieren.
12. ESP nur so lange und mit so wenigen Rechten wie nötig lesen.
13. Selector strikt validieren.
14. Fallback auf Default implementieren.
15. `plmf theme current` implementieren.
16. `plmf theme list` implementieren.
17. `plmf theme search` als lokale Suche implementieren.
18. `sudo plmf theme set` mit atomarem Schreiben implementieren.
19. `sudo plmf theme reset` implementieren.
20. Persistenz über NixOS-Rebuild testen.
21. Entfernen eines ausgewählten Themes aus der Allowlist testen.
22. `plmf theme test` mit QEMU-Workflow verbinden.
23. Minimal-Testtheme hinzufügen.
24. Theme-Wechsel zwischen zwei echten Themes testen.
25. ZOOT-Theme-Grundgerüst bauen.
26. vorhandene Bash-Animation als visuelle Referenz übernehmen.
27. responsive Positionierung implementieren.
28. LUKS-Prompt im ZOOT-Stil implementieren.
29. ZOOT-Initialisierungssequenz implementieren.
30. Welcome-Sequenz implementieren.
31. READY_HOLD und subtilen Flicker implementieren.
32. Standard-Handoff an greetd testen.
33. nur falls sichtbar nötig `retain-splash` optimieren.
34. vollständige VM-Testmatrix ausführen.
35. `nix flake check` und Systembuild ausführen.
36. erst danach auf `nyx` testen.
37. danach auf `aether` testen.
38. Fehler und Messwerte dokumentieren.
39. Branch erst nach realen Tests als merge-fähig betrachten.

## Erfolgsbedingungen

Das Feature gilt erst als stabil, wenn:

- LUKS unverändert zuverlässig funktioniert.
- kein eigener Code das Passwort verarbeitet.
- Plymouth bereits in der Passwortphase aktiv ist.
- nach Unlock kein absichtlich erzeugter schwarzer Screen erscheint.
- ZOOT vollständig läuft.
- READY_HOLD bis zum Greeter sichtbar bleibt.
- mindestens zwei Themes gebündelt sind.
- `plmf theme set` ohne NixOS-Rebuild zwischen diesen Themes wechselt.
- Runtime-Auswahl einen normalen Rebuild überlebt.
- `plmf theme reset` sauber auf den deklarativen Default zurückfällt.
- ungültiger Selector den Boot nicht blockiert.
- Theme-Tests in QEMU möglich sind.
- `nyx` real getestet ist.
- `aether` real getestet ist.
- Rollback funktioniert.

## Offene Fragen / Unklarheiten

### UNKLAR: endgültiger CLI-Name

Aktuell wird `plmf` geplant.

Falls sich bei der Umsetzung ein Namenskonflikt mit einem vorhandenen Programm zeigt, muss vor einer Umbenennung Rücksprache gehalten werden.

### UNKLAR: LUKS-Prompt-Design

Technische Architektur steht fest.

Offen ist nur die Optik:

- minimaler ZOOT-Lockscreen
- voller ZOOT-HUD-Look
- reduzierter Prompt vor der eigentlichen Animation

### UNKLAR: gleichzeitiges Multi-Monitor-Verhalten

Responsive Einzelauflösungen werden unterstützt.

Mehrere gleichzeitig aktive Displays, insbesondere bei Intel/NVIDIA PRIME auf `aether`, müssen real getestet werden.

### UNKLAR: Umfang externer Theme-Plugins

Version 1 soll fremde native Plymouth-Plugins nicht automatisch in die initrd aufnehmen.

Falls später ein gewünschtes Internet-Theme ein eigenes natives Plugin benötigt, muss dieses Theme separat sicherheitsgeprüft werden.

## Nicht-Ziele für Version 1

- keine Installation beliebiger Themes direkt per URL über `plmf`
- kein automatisches Ausführen fremder Theme-Installer
- kein Runtime-Download im initrd
- kein eigener LUKS-Passwortdienst
- kein Fullscreen-Video als primäre ZOOT-Implementierung
- kein direkter Merge nach `main` ohne VM- und Hardwaretests
