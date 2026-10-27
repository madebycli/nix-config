# Wallpaper und Farbe für Helium

Das Noctalia-Plugin exportiert das Wallpaper standardmäßig nach
`~/Bilder/Noctalia-Helium/noctalia-wallpaper.jpg` und kann das lokale
Startseitenbild im Helium-Default-Profil automatisch aktualisieren. Die
Einstellungen für Export, automatische Übernahme, Monitor, Unschärfe und Körnung
stehen in Noctalia unter Plugins zur Verfügung. Ein neuer Tab zeigt das neue
Bild; bereits offene Tabs können das alte Bild bis zum Neuladen behalten.

Der Befehl `helium-noctalia-color` übernimmt einmalig Noctalias aktive
Primärfarbe in Heliums eigenes Farbschema und aktiviert bei eingeschalteter
Wallpaper-Synchronisierung das lokale Startseitenbild. Helium muss vollständig
geschlossen sein. Danach Helium normal starten. Der Befehl ändert die Farbe
nicht automatisch bei späteren Wallpaperwechseln und muss erneut ausgeführt
werden. Das Plugin startet keine Browser-Debugging-Verbindung.

Vor dem ersten Ersetzen eines vorhandenen lokalen Helium-Hintergrunds wird
unter `~/.local/share/noctalia/helium-wallpaper/` eine Kopie gesichert. Beim
Abschalten der Synchronisierung wird sie wiederhergestellt, sofern das aktuelle
Bild inzwischen nicht anderweitig geändert wurde. Andere Helium-Profile werden
nicht synchronisiert. Python 3 mit Pillow und bubblewrap sind erforderlich.

Die Bildverarbeitung läuft in einer bubblewrap-Sandbox ohne Zugriff auf das
Home-Verzeichnis oder Netzwerk. Sie sieht das ausgewählte Bild, das Skript und
den lesbaren Nix-Store. Laufzeit, Speicher und Bildgröße sind begrenzt. Wenn
die Sandbox nicht startet, wird kein Bild verarbeitet. Das Plugin selbst muss
weiterhin als Benutzer in die gewählten Ausgabe- und Helium-Profildateien
schreiben können; der Farbbefehl bearbeitet die Profileinstellungen einmalig.

Die NixOS-Konfiguration installiert Plugin, Farbbefehl und bubblewrap über
Home Manager, wenn Noctalia ausgewählt ist. Bei einem neuen Noctalia-Profil wird
das Plugin einmalig aktiviert und die aktuelle Unschärfe/Körnung als Anfangswert
gesetzt. Bestehende Noctalia-Einstellungen bleiben unverändert. Nach einer
Neuinstallation muss ein Wallpaper verfügbar und in Noctalia ausgewählt sein;
Helium benötigt ein angelegtes Default-Profil. Bei geschlossenem Helium wird
`helium-noctalia-color` einmalig ausgeführt, um Farbe und Hintergrund zu
aktivieren. Das Wallpaper selbst und das Helium-Profil sind keine Bestandteile
dieses Repositories.
