# Rust lernen mit NixOS und VSCodium

Das Feature heißt `rust-dev`. Es ist auf `nyx` und `aether` zunächst ausgeschaltet.

## Einschalten und ausschalten

```bash
nixctl on rust-dev
nixctl apply
```

Alternativ in `hosts/<host>/features.nix` setzen:

```nix
my.features.rust-dev.enable = true;
```

Nach dem Aktivieren ein neues Terminal öffnen. Bei einer bereits laufenden
VSCodium-Instanz alle Fenster schließen und VSCodium neu starten, damit die neue
Toolchain und `RUST_SRC_PATH` verfügbar sind.

Zum Ausschalten:

```bash
nixctl off rust-dev
nixctl apply
```

Deine Projekte und Editor-Einstellungen bleiben erhalten. `settings.json` bleibt
eine normale, schreibbare Benutzerdatei. Du kannst Einstellungen, das Farbthema
und zusätzliche Erweiterungen in VSCodium ändern. Das gilt auch für die
NoctaliaTheme-Erweiterung und Noctalias VSCode-Template.

Die Rust-Vorgaben werden nur beim ersten Start ohne vorhandene Einstellungsdatei
angelegt. Vorhandene eigene Einstellungen (auch JSON mit Kommentaren) werden
nicht überschrieben. Die früher vom Rust-Modul angelegte Nix-Store-Verknüpfung
wird beim nächsten Aktivieren vor Home Managers Bereinigung in eine schreibbare
Datei umgewandelt. Ihr vorheriger Inhalt bleibt zusätzlich als
`settings.json.before-rust-dev-writable` erhalten. VSCodium vor dieser ersten
Migration schließen und nach dem Systemwechsel erneut öffnen.

Die Rust-Werkzeuge verwenden stabile Systempfade, damit Änderungen am Nixpkgs-Pin
keine veralteten Nix-Store-Pfade in neu angelegten Einstellungen hinterlassen.

## Wenn noch ein altes `nixctl` installiert ist

Falls `rust-dev` unbekannt ist, fehlt die neue Schalterzeile im verwendeten
Checkout. Aktualisiere nach dem Merge zuerst den Code. Wenn `nixctl apply` noch
`unrecognized arguments: --out-link` meldet, starte einmal die korrigierte
Version direkt aus dem aktualisierten Checkout:

```bash
cd ~/nix-config
nx pull
nix run .#nixctl -- on rust-dev
nix run .#nixctl -- apply
```

Verwende bei einem anderen Repository-Pfad deinen tatsächlichen Checkout.
`nixctl` liest den konfigurierten Pfad aus `/etc/nixctl.conf`. Nach dem
Systemwechsel ist auch das installierte `nixctl` aktualisiert.

## Was enthalten ist

- `rustc`: Rust-Compiler.
- `cargo`: Projekte erstellen, Abhängigkeiten verwalten, bauen und testen.
- `rustfmt` und Clippy: Formatierung und hilfreiche Code-Hinweise.
- `rust-analyzer` und Rust-Standardbibliotheksquellen: Vervollständigung, Navigation und Fehleranzeigen.
- GCC als Linker und `pkg-config` für spätere Projekte mit nativen Bibliotheken.
- VSCodium mit rust-analyzer, CodeLLDB und Even Better TOML.
- `rustlings`: kleine interaktive Übungen.
- `opencode`: Coding-Assistent im Terminal, direkt im Projekt nutzbar.

Compiler, Cargo und Werkzeuge stammen aus demselben Nixpkgs-Pin. Installiere für
dieses Setup kein zusätzliches Rust über `rustup` oder die automatische
Editor-Installation. Prüfe bei einer bereits vorhandenen Rust-Installation mit
`type -a rustc cargo`, welche Version dein Terminal tatsächlich verwendet.

## Dein erstes Projekt

```bash
mkdir -p ~/Projekte
cd ~/Projekte
cargo new hallo-rust
cd hallo-rust
cargo run
cargo test
codium .
```

Bearbeite `src/main.rs`, zum Beispiel:

```rust
fn main() {
    let name = "Rust";
    println!("Hallo, {name}!");
}
```

Die neu angelegten Rust-Vorgaben aktivieren Formatierung beim Speichern und
Clippy-Hinweise. Wenn bereits eigene Einstellungen vorhanden waren, kannst du
Formatierung und `rust-analyzer.check.command = clippy` im Editor einschalten. Dieselben Prüfungen funktionieren im Terminal:

```bash
cargo fmt --check
cargo clippy
cargo test
```

Beim ersten Projekt mit externen Crates lädt Cargo Abhängigkeiten von crates.io.
Ein Projekt mit C-/Systembibliotheken kann später zusätzliche Bibliotheken in
einer projektspezifischen Nix-Entwicklungsumgebung benötigen.

## OpenCode im Rust-Projekt

OpenCode wird zusammen mit `rust-dev` installiert. Nach dem Systemwechsel kannst
du es im Projektordner starten:

```bash
cd ~/Projekte/hallo-rust
opencode
```

Anbieter und Modell richtest du in OpenCode selbst ein. Das NixOS-Modul hinterlegt
keine API-Schlüssel oder Modellvorgaben und startet keinen zusätzlichen Dienst.
Deine persönlichen OpenCode-Einstellungen bleiben unverwaltet.

## Debuggen

Öffne das Projekt mit `codium .`, setze links neben einer Codezeile einen
Haltepunkt und starte **Ausführen und Debuggen**. Wähle bei der Einrichtung
**LLDB** und lasse CodeLLDB die Cargo-Konfiguration erzeugen. Falls der
Editor keine Konfiguration anbietet, lege `.vscode/launch.json` im Projekt an:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "type": "lldb",
      "request": "launch",
      "name": "Rust: Debug",
      "cargo": { "args": ["build"] },
      "cwd": "${workspaceFolder}",
      "args": []
    }
  ]
}
```

Für Workspaces oder mehrere Binärprogramme wählst du das gewünschte Cargo-Target
in der Debug-Konfiguration aus.

## Übungen und Nachschlagen

```bash
mkdir -p ~/Projekte
cd ~/Projekte
rustlings init
cd rustlings
rustlings
```

- [The Rust Programming Language](https://doc.rust-lang.org/book/): offizielles Rust-Buch.
- [Rust by Example](https://doc.rust-lang.org/rust-by-example/): ausführbare Beispiele.
- [Standardbibliothek](https://doc.rust-lang.org/std/): Typen und Funktionen nachschlagen.
