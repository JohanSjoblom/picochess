# Récapitulatif du projet — Intégration Novag Citrine dans picochess v4

## Objectif
Connecter le Novag Citrine en Bluetooth (`/dev/rfcomm1`) comme board e-chess dans picochess v4,
en remplacement ou en complément du board DGT.

---

## ⚠️ Note de révision — convention de nommage « CITRINE »

Le projet a été harmonisé : l'identifiant interne du board est désormais **`CITRINE`** partout
(et non plus `NOVAG`). Il faut distinguer **deux niveaux de nommage**, car ils ne changent pas
ensemble :

| Élément | Valeur | Modifiable librement ? |
|---|---|---|
| Classes du driver | `NovagBoard`, `NovagDisplay` | ❌ Non (référencées par les imports de `picochess.py`) |
| Fonctions helper | `_uci_to_novag`, `_novag_to_move` | ❌ Non sauf renommage des deux côtés |
| Attribut/paramètre interne | `citrine_board` / `self._citrine_board` | ✅ Oui (interne à `board.py`) |
| **Nom du membre d'enum** | `EBoard.CITRINE` | ⚠️ Doit matcher l'`.ini` (voir ci-dessous) |
| Valeur du membre d'enum | `"B00_eboard_citrine_menu"` | sert au menu/traduction |
| **Token de l'`.ini`** | `board-type = citrine` | ⚠️ Doit matcher le nom du membre |
| Libellé web | `"Novag Citrine"` | ✅ cosmétique |

> Les classes gardent volontairement le préfixe **Novag** (marque du matériel), tandis que
> l'identifiant picochess du board est **citrine**. C'est normal et cohérent.

### Point critique : `EBoard[...]` est une recherche **par NOM**, pas par valeur
Dans `picochess.py` (`async def main()`) :
```python
board_type = dgt.util.EBoard[args.board_type.upper()]   # lookup par NOM de membre
```
Pour que la Citrine se connecte, **trois éléments doivent dire « citrine »** :
1. `dgt/util.py` → le **nom du membre** est `CITRINE`
2. `picochess.ini` → `board-type = citrine`
3. `picochess.py` → références `EBoard.CITRINE`

Si l'un des trois diverge :
- nom de membre absent (`AttributeError`) → crash au démarrage ;
- token `.ini` non résolu (`KeyError`) → **repli silencieux sur DGT** (la Citrine n'est jamais
  chargée, sans message d'erreur). C'est la cause typique d'un « board qui ne se connecte plus ».

La **valeur** du membre (`"B00_eboard_citrine_menu"`) ne sert qu'au menu et à la traduction,
jamais à la résolution du `board-type`.

---

## Fichiers NOUVEAUX

### `/opt/picochess/eboard/citrine/__init__.py`
Fichier vide — marqueur de package Python.

### `/opt/picochess/eboard/citrine/board.py`
Driver complet du Novag Citrine. Contient :
- `NovagBoard` — connexion série async, lecture des coups, envoi des coups moteur
- `NovagDisplay` — intercepte `COMPUTER_MOVE` et forwarde à la Citrine
  (paramètre/attribut renommé en `citrine_board` / `self._citrine_board`)
- Séquence de connexion : `Xon` → `N` → `Uon` × 2 (ordre critique)
- Ré-envoi de `Uon` après chaque `New Game` reçu
- Double envoi du coup moteur (`mb8c6` × 2) pour activer les LEDs
- `pos960=518` pour démarrer en chess standard
- `TAKE_BACK(take_back="TAKEBACK")` compatible avec picochess (take-back « T » validé)
- Stubs no-op pour toutes les méthodes du protocole `EBoard`
- **Inversion du plateau via `F`** : sur `PLAY_MODE`, `NovagDisplay` oriente la Citrine
  pour que le plateau physique s'inverse (Noirs en bas) quand l'utilisateur joue Noir
  (cf. section « Inversion du plateau » plus bas)

---

## Inversion du plateau quand l'utilisateur joue Noir (envoi de `F`)

Commande Citrine `F` = « flip colour (board takes opposite side) ». C'est une **bascule**
(toggle), pas un set absolu. On veut que le plateau physique s'inverse (Noirs en bas) quand
l'utilisateur passe en Noir, pour coller à l'affichage web.

Implémentation dans `board.py` (5 ajouts, take-back « T » non touché) :

1. **`NovagBoard.__init__`** — attribut d'orientation :
```python
# False = computer plays Black (défaut après N), True = computer plays White
self._computer_is_white = False
```

2. **`NovagBoard.set_computer_color()`** — envoi idempotent de `F` :
```python
async def set_computer_color(self, computer_white: bool) -> None:
    if not self._connected:
        return
    if computer_white != self._computer_is_white:
        await self._send("F")
        self._computer_is_white = computer_white
        logger.info("NovagBoard: 'F' sent — computer_is_white=%s", computer_white)
```
> `F` n'est envoyé que si l'orientation cible diffère de l'actuelle → pas de désync.

3. **`NovagBoard.new_game()`** — reset au défaut : `self._computer_is_white = False`.

4. **`NovagBoard._handle_line`** (bouton New Game) — resync **sans** `F` (le `N` matériel a
   déjà remis le plateau au défaut) :
```python
self._turn = chess.WHITE
self._computer_is_white = False
```

5. **`NovagDisplay.message_consumer`** (branche `PLAY_MODE`) — via l'attribut `citrine_board` :
```python
computer_white = (mode == PlayMode.USER_BLACK)   # user Noir ⇒ computer Blanc ⇒ F
await self._citrine_board.set_computer_color(computer_white)
```

Déroulé : bascule en Noir (web/pendule) → `PLAY_MODE(USER_BLACK)` → `set_computer_color(True)`
→ `F` envoyé → Citrine inversée. Retour en Blanc ou nouvelle partie → `F` renvoyé uniquement
si nécessaire pour revenir au défaut.

> Si jamais le sens du `F` est inversé physiquement (plateau retourné quand on joue Blanc),
> inverser la condition : `computer_white = (mode == PlayMode.USER_WHITE)`.

### `/etc/systemd/system/rfcomm_citrine.service`
Service systemd qui bind la Citrine à `/dev/rfcomm1` au démarrage.
```ini
[Unit]
Description=Bind Novag Citrine (98:D3:31:F5:30:AD) to /dev/rfcomm1
After=bluetooth.target bluetooth-mesh.target
Requires=bluetooth.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/sleep 5
ExecStart=/usr/bin/rfcomm bind 1 98:D3:31:F5:30:AD
ExecStop=/usr/bin/rfcomm release 1
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## Fichiers MODIFIÉS

### `/opt/picochess/dgt/util.py`
Ajout du membre `CITRINE` dans la classe `EBoard` (menu système). **Le nom du membre est
`CITRINE`** (c'est lui qui doit matcher `board-type = citrine` de l'`.ini`) :
```python
class EBoard(MyEnum):
    CERTABO   = "B00_eboard_certabo_menu"
    CHESSLINK = "B00_eboard_chesslink_menu"
    CHESSNUT  = "B00_eboard_chessnut_menu"
    DGT       = "B00_eboard_dgt_menu"
    ICHESSONE = "B00_eboard_ichessone_menu"
    CITRINE   = "B00_eboard_citrine_menu"       # ← AJOUTÉ (nom = CITRINE)
    NOEBOARD  = "B00_eboard_noeboard_menu"

    @classmethod
    def items(cls):
        return [EBoard.CERTABO, EBoard.CHESSLINK, EBoard.CHESSNUT,
                EBoard.DGT, EBoard.ICHESSONE, EBoard.CITRINE, EBoard.NOEBOARD]  # ← CITRINE ajouté
```
> ⚠️ Le **nom du membre** (`CITRINE`) et la référence dans `items()` (`EBoard.CITRINE`) doivent
> être identiques. Une déclaration `NOVAG = …` avec un `items()` qui appelle `EBoard.CITRINE`
> (ou l'inverse) lève une `AttributeError` au montage du menu.

### `/opt/picochess/dgt/translate.py`
Ajout du bloc de traduction **`eboard_citrine_menu`** (le text_id dérive de la valeur de l'enum
`B00_eboard_citrine_menu`, préfixe `B00_` retiré), avant le bloc `eboard_noeboard_menu` :
```python
if text_id == "eboard_citrine_menu":
    entxt = Dgt.DISPLAY_TEXT(
        web_text="Novag Citrine",
        large_text="Nov Citrin",
        medium_text="citrin  ",
        small_text="citri",
    )
    detxt = entxt
    nltxt = entxt
    frtxt = entxt
    estxt = entxt
    ittxt = entxt
```
> ⚠️ Le text_id doit être `eboard_citrine_menu` (et non `eboard_novag_menu`) pour correspondre
> à la valeur du membre d'enum, sinon le libellé du menu n'est pas traduit.

### `/opt/picochess/configuration.py`
Ajout de `"citrine"` dans le texte d'aide de `--board-type` (cosmétique) :
```
'Type of e-board: "dgt", "certabo", "chesslink", "chessnut", "ichessone",
 "citrine" or "noeboard" ...'
```

### `/opt/picochess/picochess.py`
1. Imports :
```python
from eboard.citrine.board import NovagBoard
from eboard.citrine.board import NovagDisplay
```
> Les **noms de classes** `NovagBoard`/`NovagDisplay` ne changent pas : si on les renomme, il
> faut modifier ces imports **et** les instanciations ci-dessous.

2. Bloc elif dans `async def main()` :
```python
elif board_type == dgt.util.EBoard.CITRINE:
    dgtboard = NovagBoard(main_loop)
    if args.dgt_port:
        connected = await dgtboard.connect(args.dgt_port)
        if not connected:
            logger.error("NovagBoard: connexion impossible sur %s", args.dgt_port)
    else:
        logger.error("NovagBoard: aucun port défini (dgt-port manquant)")
```

3. Instanciation du consumer après `my_pgn_display` (appel **positionnel** → le nom du
   paramètre `citrine_board` côté `board.py` n'a pas d'importance ici) :
```python
if board_type == dgt.util.EBoard.CITRINE:
    my_novag_display = NovagDisplay(dgtboard, main_loop)
    non_main_tasks.add(asyncio.create_task(my_novag_display.message_consumer()))
```

4. **Bloc CITRINE dans le handler `Event.SWITCH_SIDES`** (branche `NORMAL`/`BRAIN`/`TRAINING`)
   pour autoriser le moteur à jouer le premier coup quand l'utilisateur passe en Noir
   (cf. section « Correctif — moteur joue le premier coup ») :
```python
                    if cond1 or cond2:
                        # Novag Citrine: switching sides at game start is how the
                        # engine is asked to play the first move. Clear the new-game
                        # flag so EVT_BEST_MOVE does not discard the move as "stale".
                        # Scoped to CITRINE — no other board is affected.
                        if self.board_type == dgt.util.EBoard.CITRINE:
                            self.state.newgame_happened = False
                        self.state.time_control.reset_start_time()
                        await self.think(msg)  # PLAY_MODE
```

### `/opt/picochess/server.py`  ← **NOUVELLE MODIFICATION**

**1. Libellé du board dans l'interface web** (rendu de `clock.html`).
Le dictionnaire `_eboard_labels` traduit le membre `EBoard` actif en texte affiché dans le
pied de page / le statut web. Ajout de l'entrée `CITRINE` :
```python
import dgt.util as _dgt_util
_eboard_labels = {
    _dgt_util.EBoard.DGT:       "DGT",
    _dgt_util.EBoard.CERTABO:   "Certabo",
    _dgt_util.EBoard.CHESSLINK: "ChessLink",
    _dgt_util.EBoard.CHESSNUT:  "Chessnut",
    _dgt_util.EBoard.ICHESSONE: "iChessOne",
    _dgt_util.EBoard.CITRINE:   "Novag Citrine",   # ← AJOUTÉ
    _dgt_util.EBoard.NOEBOARD:  "No e-board",
}
eboard_name = _eboard_labels.get(ModeInfo.get_eboard_type(), "DGT")
```
> **Effet** : l'interface web affiche « Novag Citrine » au lieu de retomber sur le défaut
> « DGT ». Modification purement cosmétique (affichage), sans impact sur la connexion.

**2. ⚠️ À FAIRE — whitelist du sélecteur de board web (`action == "eboard"`).**
La sélection du board depuis la page *Settings* web valide la valeur reçue contre un ensemble
qui **n'inclut pas `citrine`** :
```python
_valid_eboards = {"dgt", "certabo", "chesslink", "chessnut", "ichessone", "none"}
```
Conséquence : choisir « Novag Citrine » dans le menu déroulant web est **silencieusement
ignoré** (la condition `if eboard_type in _valid_eboards` est fausse → rien n'est écrit dans
l'`.ini`, pas de reboot). Tant que cette ligne n'est pas corrigée, le board ne peut être
sélectionné que via `picochess.ini` ou le menu DGT physique. Correctif :
```python
_valid_eboards = {"dgt", "certabo", "chesslink", "chessnut", "ichessone", "citrine", "none"}
```
> Vérifier aussi que le `<select>` correspondant du template propose bien l'option `citrine`.

### `/opt/picochess/picochess.ini`
```ini
board-type = citrine
dgt-port   = /dev/rfcomm1
```
> La ligne `board-type` doit être **non commentée** et dans la bonne section. Une ligne
> commentée (`#board-type = …`) ou absente → repli silencieux sur DGT.

### `/etc/systemd/system/picochess.service`
Ajout de la dépendance au service rfcomm dans `[Unit]` :
```ini
After=multi-user.target rfcomm_citrine.service
Wants=rfcomm_citrine.service
```

### `/root/.asoundrc` (ou `/etc/asound.conf`)
Configuration audio pour que SoX fonctionne en root (annonces vocales) :
```
pcm.!default {
    type hw
    card 2
    device 0
}
ctl.!default {
    type hw
    card 2
}
```

---

## Correctif — moteur joue le premier coup (utilisateur Noir)

La bascule de camp provient du **web display** ou de la **pendule DGT** (jamais du Citrine
lui-même). Elle déclenche `Event.SWITCH_SIDES`, traité dans `picochess.py` :
`SWITCH_SIDES` → inversion de `play_mode` → si c'est maintenant le tour du moteur,
`think()` → `Event.BEST_MOVE` → `Message.COMPUTER_MOVE` → `NovagDisplay.send_move()`.

**Symptôme** : aucun premier coup joué par le moteur quand on bascule en Noir avant
d'avoir joué.

**Cause** : le drapeau `newgame_happened` est mis à `True` par `Event.NEW_GAME` et n'est
remis à `False` que dans `process_fen` (traitement d'un vrai coup plateau). Le handler
`BEST_MOVE` contient un garde-fou anti-course qui **jette** le coup moteur si
`newgame_happened` est `True` (« discarding stale engine move »).

Or le Citrine est le **seul driver piloté par événements de coups** (`KEYBOARD_MOVE`) et
non par flux FEN continu. Quand on bascule en Noir *avant tout coup*, aucun `process_fen`
n'a encore tourné → `newgame_happened` reste coincé à `True` → le premier coup du moteur
est jeté. Les boards à balayage (DGT, Chesslink, Certabo, Chessnut, IChessOne) alimentent
picochess par un flux d'`Event.FEN` qui passe par `process_fen`, où le drapeau est nettoyé.

**Correctif** : bloc `CITRINE` dans le handler `SWITCH_SIDES` qui lève `newgame_happened`
juste avant `think()` (voir `picochess.py`, modification n°4 ci-dessus). Le reset est
logiquement correct (la nouvelle partie a eu lieu *avant* le démarrage de `think()`,
donc le coup n'est pas réellement périmé) et **strictement limité à CITRINE** : aucun autre
board n'est impacté.

---

## Fonctionnalités validées
- ✅ Connexion Bluetooth au démarrage automatique
- ✅ Coups humains remontés vers picochess
- ✅ Coups moteur envoyés à la Citrine avec LEDs
- ✅ Mode Referee maintenu après New Game
- ✅ Démarrage en Chess standard (pos960=518)
- ✅ Take-back « T » fonctionnel
- ✅ Horloge DGT Pi synchronisée
- ✅ Libellé « Novag Citrine » affiché dans l'interface web (`server.py`)

## Correctifs / points à valider sur le matériel
- 🔧 **`picochess.py`** — bloc `CITRINE` dans `SWITCH_SIDES` → le moteur doit jouer le premier
  coup quand l'utilisateur passe en Noir (bascule web/pendule)
- 🔧 **`board.py`** — envoi de `F` sur `PLAY_MODE` → la Citrine doit s'inverser (Noirs en bas)
  quand l'utilisateur passe en Noir
- 🔧 **`server.py`** — ajouter `"citrine"` à `_valid_eboards` pour permettre la sélection du
  board depuis la page *Settings* web (sinon sélection ignorée)

---

## Commandes utiles

### Démarrage manuel (debug)
```bash
sudo systemctl stop picochess.service
sudo rfcomm bind 1 98:D3:31:F5:30:AD
cd /opt/picochess && sudo /opt/picochess/venv/bin/python3 picochess.py \
    --board-type citrine --dgt-port /dev/rfcomm1 --log-level debug --log-file pico.log
```
> Si la Citrine se connecte avec `--board-type citrine` en CLI mais pas via l'`.ini`, le
> problème est dans `picochess.ini` (ligne commentée, manquante, ou mauvaise section).

### Vérifier la cohérence du nommage
```bash
grep -nE "NOVAG|CITRINE" /opt/picochess/dgt/util.py      # nom du membre = CITRINE
grep -i  "board-type"     /opt/picochess/picochess.ini    # = citrine, non commenté
grep -nE "CITRINE"        /opt/picochess/picochess.py      # EBoard.CITRINE
```

### Surveillance des logs
```bash
tail -f /opt/picochess/logs/pico.log | grep -i "novag\|human\|forward\|move"
```

Pour diagnostiquer le premier coup moteur et l'inversion :
```bash
tail -f /opt/picochess/logs/pico.log | grep -i \
    "discarding stale engine move\|SWITCH_SIDES\|COMPUTER_MOVE\|'F' sent\|PLAY_MODE"
```
- `'F' sent — computer_is_white=True` doit apparaître à la bascule en Noir (sinon `PLAY_MODE`
  n'atteint pas le consumer).
- `discarding stale engine move` à la bascule = `newgame_happened` resté `True` →
  vérifier le bloc CITRINE du handler `SWITCH_SIDES`.

### Appairage Citrine (une seule fois)
```bash
sudo bluetoothctl
  agent on
  scan on
  pair 98:D3:31:F5:30:AD    # PIN : 1032
  trust 98:D3:31:F5:30:AD
  quit
```

---

## Pour repasser en board DGT
Dans `/opt/picochess/picochess.ini` :
```ini
board-type = dgt
dgt-port   = /dev/ttyACM0
```
