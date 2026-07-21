# SETUP — VPS-Arena auf einem eigenen Server aufsetzen

Dieser Fahrplan führt dich **vom leeren Server bis zur laufenden Arena** — ohne
Vorwissen. Beispiel-Anbieter: **Hetzner** (deutsch, günstig, DSGVO). Mit anderen
Anbietern (Netcup, Contabo …) sind die Schritte identisch, nur die Weboberfläche
zum Mieten sieht anders aus.

> Kosten-Orientierung: **Hetzner CAX21** (4 CPU, 8 GB RAM) ≈ **6,50 €/Monat** —
> reicht für das komplette System **inklusive** eines kleinen lokalen KI-Modells.
> Ohne lokale KI genügt der kleinste (~4 €/Monat).

---

## 0. Was du brauchst

- Eine Kreditkarte oder PayPal (für den Server-Mietvertrag)
- 30 Minuten Zeit
- Einen Computer mit Terminal (Mac/Linux: „Terminal"; Windows: „PowerShell")

---

## 1. Server mieten (Hetzner)

1. Konto anlegen auf **console.hetzner.cloud**
2. **New Project** → Name z. B. `arena`
3. **Add Server**:
   - **Location:** Falkenstein oder Nürnberg (Deutschland)
   - **Image:** **Ubuntu 24.04**
   - **Type:** **CAX21** (Arm, 4 CPU, 8 GB) — oder CAX11 (~4 €) ohne lokale KI
   - **SSH Key:** falls du keinen hast → siehe Kasten unten (empfohlen), sonst
     Passwort wählen
   - **Create & Buy now**
4. Nach ~30 Sekunden bekommst du eine **IP-Adresse**, z. B. `91.99.12.34`.
   Die brauchst du gleich.

> **SSH-Key in 1 Minute (empfohlen, sicherer als Passwort):**
> Im eigenen Terminal:
> ```bash
> ssh-keygen -t ed25519        # 3× Enter drücken
> cat ~/.ssh/id_ed25519.pub    # den ausgegebenen Text bei Hetzner als SSH-Key einfügen
> ```

---

## 2. Mit dem Server verbinden

Im **eigenen** Terminal (IP durch deine ersetzen):

```bash
ssh root@91.99.12.34
```

Beim ersten Mal „yes" tippen. Du bist jetzt **auf dem Server** — alle folgenden
Befehle laufen dort.

---

## 3. Grundausstattung installieren

```bash
apt update && apt -y upgrade
apt -y install python3 python3-venv python3-pip git
```

Optional, aber empfohlen — einen eigenen Benutzer statt „root" nutzen:

```bash
adduser arena              # Passwort vergeben, Rest mit Enter
usermod -aG sudo arena
su - arena                 # ab hier als Benutzer 'arena'
```

---

## 4. Arena holen und installieren

```bash
git clone https://github.com/Rawkeep/vps-arena.git
cd vps-arena
git checkout claude/vps-ai-agent-sqlite-hnrccy   # aktueller Entwicklungsstand

python3 -m venv .venv          # isolierte Umgebung
source .venv/bin/activate      # aktivieren (Prompt zeigt jetzt (.venv))
pip install -e .               # Arena installieren (nur pydantic als Abhängigkeit)
```

Kurzer Funktionstest — muss ohne Fehler durchlaufen:

```bash
python demo.py
```

Wenn du am Ende die „Survival-Bilanz" siehst: **alles läuft.** 🎉

---

## 5. Erste Schritte von Hand

```bash
arena init                                          # Datenbank anlegen
arena run "Test-Auftrag RAG-Bot" --tags rag --win --revenue 1000
arena ls                                            # zeigt den gebauten Build
```

`arena run` hat gerade ein echtes, startbares Mini-Programm erzeugt (unter
`builds/…`). Das gucken wir uns über das Gateway an (Schritt 7).

---

## 6. (Optional) Lokale KI (Ollama) installieren

Nur nötig, wenn die KI echte Texte formulieren soll. Das System läuft auch **ohne**
(dann schreibt es Standard-Texte, die Entscheidungen sind ohnehin regelbasiert).

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b        # kleines Modell (~2 GB), läuft auf 8 GB RAM
```

Arena die KI nutzen lassen — in `~/vps-arena/.env`:

```bash
echo "ARENA_USE_OLLAMA=1"          >  ~/vps-arena/.env
echo "ARENA_OLLAMA_MODEL=llama3.2:3b" >> ~/vps-arena/.env
```

> Hinweis: Auf einer CPU (ohne Grafikkarte) antwortet die KI **langsam** — für
> wenige Aufträge völlig okay, für Massenbetrieb bräuchtest du mehr Leistung.

---

## 7. Dauerbetrieb einrichten (systemd)

Damit **Autopilot** (holt Aufträge) und **Gateway** (zeigt alle Tools) automatisch
laufen — auch nach einem Neustart. Zwei kleine Dienst-Dateien.

Zuerst einen Auftrags-Ordner + Umgebung festlegen (Pfade ggf. anpassen, falls du
nicht Benutzer `arena` heißt):

```bash
mkdir -p ~/vps-arena/inbox ~/vps-arena/data ~/vps-arena/builds
```

**7a. Gateway-Dienst** (die öffentliche Übersicht):

```bash
sudo tee /etc/systemd/system/arena-gateway.service >/dev/null <<'UNIT'
[Unit]
Description=VPS-Arena Gateway (Lobby)
After=network.target

[Service]
User=arena
WorkingDirectory=/home/arena/vps-arena
EnvironmentFile=/home/arena/vps-arena/.env
Environment=ARENA_DB_PATH=/home/arena/vps-arena/data/arena.db
Environment=ARENA_ARTIFACTS_DIR=/home/arena/vps-arena/builds
Environment=PORT=8080
ExecStart=/home/arena/vps-arena/.venv/bin/arena gateway --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
```

**7b. Autopilot-Dienst** (holt sich Aufträge alle 60 s aus `inbox/`):

```bash
sudo tee /etc/systemd/system/arena-autopilot.service >/dev/null <<'UNIT'
[Unit]
Description=VPS-Arena Autopilot (Job-Picking)
After=network.target

[Service]
User=arena
WorkingDirectory=/home/arena/vps-arena
EnvironmentFile=/home/arena/vps-arena/.env
Environment=ARENA_DB_PATH=/home/arena/vps-arena/data/arena.db
Environment=ARENA_ARTIFACTS_DIR=/home/arena/vps-arena/builds
ExecStart=/home/arena/vps-arena/.venv/bin/arena autopilot --dir /home/arena/vps-arena/inbox --interval 60
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
```

Beide starten und dauerhaft aktivieren:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now arena-gateway arena-autopilot
sudo systemctl status arena-gateway --no-pager     # sollte "active (running)" zeigen
```

---

## 8. Firewall + Zugriff

Port 8080 (Gateway) und SSH freigeben:

```bash
sudo apt -y install ufw
sudo ufw allow OpenSSH
sudo ufw allow 8080/tcp
sudo ufw --force enable
```

Jetzt im Browser öffnen: **http://DEINE-IP:8080** → die **Arena-Lobby** mit allen
gebauten Tools erscheint.

Einen Auftrag „einwerfen" (auf dem Server) — der Autopilot baut ihn binnen 60 s:

```bash
echo '# DSGVO-Chatbot für Kanzlei
Ein Chatbot, der Dokumente durchsucht, per API erreichbar.' > ~/vps-arena/inbox/auftrag1.md
```

Danach Lobby neu laden — das neue Tool ist da. Ergebnis eintragen:

```bash
cd ~/vps-arena && source .venv/bin/activate
arena ls                                   # Build-ID ablesen
arena score build:<id> --win --revenue 4200
```

---

## 9. (Optional) Eigene Domain + HTTPS

Wenn du statt `http://IP:8080` eine echte Adresse wie `https://arena.deinedomain.de`
willst — am einfachsten mit **Caddy** (macht HTTPS automatisch):

```bash
sudo apt -y install debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt -y install caddy
```

DNS: einen A-Record `arena.deinedomain.de` → deine Server-IP setzen. Dann:

```bash
sudo tee /etc/caddy/Caddyfile >/dev/null <<'CADDY'
arena.deinedomain.de {
    reverse_proxy 127.0.0.1:8080
}
CADDY
sudo systemctl restart caddy
```

Fertig — `https://arena.deinedomain.de` läuft mit gültigem Zertifikat. (Dann in
Schritt 8 den Port 8080 wieder schließen: `sudo ufw delete allow 8080/tcp`.)

---

## 10. Backup (wichtig!)

Der ganze Zustand steckt in **einer Datei**. Backup = diese Datei kopieren:

```bash
cp ~/vps-arena/data/arena.db ~/arena-backup-$(date +%F).db
```

Für automatisch täglich: als Cronjob des Benutzers `arena`:

```bash
( crontab -l 2>/dev/null; echo "0 3 * * * cp /home/arena/vps-arena/data/arena.db /home/arena/arena-backup-\$(date +\%F).db" ) | crontab -
```

---

## Aktualisieren (neue Version einspielen)

```bash
cd ~/vps-arena
git pull
source .venv/bin/activate && pip install -e .
sudo systemctl restart arena-gateway arena-autopilot
```

---

## Wenn etwas klemmt

| Problem | Prüfen |
|---|---|
| Lobby nicht erreichbar | `sudo systemctl status arena-gateway` · Firewall (Schritt 8) |
| Autopilot baut nichts | Liegt eine Datei in `inbox/`? · `journalctl -u arena-autopilot -n 50` |
| „command not found: arena" | `source .venv/bin/activate` vergessen |
| KI antwortet nicht | `ollama list` · läuft der Ollama-Dienst? `systemctl status ollama` |

Logs live mitlesen: `journalctl -u arena-autopilot -f`
