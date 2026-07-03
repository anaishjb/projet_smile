# Guide d'installation et d'utilisation — SMILE

**SMILE** (Social Memory Integrated Learning Environment) est un agent conversationnel embarqué qui :
- reconnaît les visages en temps réel (MTCNN + FaceNet),
- transcrit la parole hors ligne en français (Vosk STT),
- génère des réponses via un LLM local (Ollama/llama3:8b),
- mémorise chaque utilisateur entre les sessions (profils JSON + résumés LLM).

---

## Lancer SMILE (utilisation courante)

Sur Windows, Ollama tourne en arrière-plan automatiquement après installation (icône barre des tâches, service sur `localhost:11434`) — pas besoin de lancer `ollama serve` manuellement. Vérifier que le service répond :
```bat
curl http://localhost:11434
```

**Terminal — SMILE :**
```bat
cd C:\Users\LUTIN\Documents\Projets\SMILE
facenet\Scripts\activate
python -m src.recognize_live
```

Au démarrage :
- Les modèles se chargent (~30–60 secondes)
- La fenêtre webcam s'ouvre
- Un nouveau visage → le robot demande le prénom
- Un visage connu → le robot salue directement
- Appuie sur `q` pour quitter proprement

---

## Prérequis système

| Composant | Version |
|-----------|---------|
| Python | 3.11+ |
| OS | Windows 10/11 |
| Webcam | branchée et non utilisée par une autre app |
| Micro | branché (index configurable dans `config.py`) |
| RAM | ≥ 8 Go |
| Java JDK 8 | requis pour le SDK Furhat (installable via le SDK Launcher) |

---

## Installation (première fois)

### 1. Installer Ollama

Télécharger depuis [ollama.com](https://ollama.com), puis :

```bat
ollama pull llama3:8b
```

### 2. Télécharger le modèle Vosk français

Télécharger depuis [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models) :

- Modèle léger (~40 Mo) : `vosk-model-small-fr-0.22`
- Modèle complet (~1.4 Go, meilleure précision) : `vosk-model-fr-0.22` ← **celui utilisé actuellement**

Dézipper dans `C:\Users\LUTIN\models\`.

### 3. Installer les dépendances Python

```bat
cd C:\Users\LUTIN\Documents\Projets\SMILE\SMILE
python -m venv facenet
facenet\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

> `furhat-remote-api==1.0.2` est déjà listé dans `requirements.txt`.

### 4. Installer Furhat (Virtual Furhat / SDK)

Furhat n'est pas un simple package pip — c'est un SDK propriétaire à demander :

1. Aller sur [furhat.io](https://furhat.io) et remplir le formulaire **Request SDK**.
2. Créer un compte sur la **Furhat Developer Zone** via l'email reçu.
3. Télécharger le **SDK Launcher** (recommandé) depuis [furhat.io/downloads](https://furhat.io/downloads), ou directement le zip du SDK pour Windows.
4. Installer **Java JDK 8** si ce n'est pas déjà fait (le Launcher peut l'installer automatiquement).
5. Lancer le SDK Launcher → il installe et démarre le **Virtual Furhat** en local.
6. Vérifier que ça fonctionne : ouvrir `http://localhost:8080` dans un navigateur (mot de passe `admin`), tester la voix et un geste depuis l'interface web.

Le code se connecte via `FurhatRemoteAPI("localhost")` (port par défaut `54321`) — aucune config supplémentaire côté Python tant que le Virtual Furhat tourne en local. Si Furhat n'est pas lancé, `speech_utils.get_furhat()` bascule automatiquement sur `pyttsx3` (pas de crash).

### 5. Créer le fichier de configuration

```bat
copy src\config_example.py src\config.py
```

Éditer `src\config.py` :

```python
BASE_DIR = "C:/Users/LUTIN/Documents/Projets/SMILE/SMILE"  # ← adapter
VOSK_MODEL_PATH = "C:/Users/LUTIN/models/vosk-model-fr-0.22/vosk-model-fr-0.22"  # ← adapter
MIC_INDEX = 20        # ← index de ton micro (voir section Dépannage)
EMBEDDINGS_FILE = f"{BASE_DIR}/data/embeddings.pkl"
```

> **Note :** `src/config.py` est dans `.gitignore` — il n'est pas versionné.

---

## Structure des données

```
data/
├── embeddings.pkl          ← base de visages {nom: vecteur 512D}
├── conversations/
│   └── <Prenom>.json       ← historique tour par tour
└── profiles/
    └── <Prenom>.json       ← profil long terme (âge, intérêts, résumé LLM)
```

Ces fichiers sont dans `.gitignore` et générés automatiquement à l'usage.

---

## Dépannage

**Trouver l'index du microphone :**
```bat
facenet\Scripts\python.exe -c "import pyaudio; p=pyaudio.PyAudio(); [print(i, p.get_device_info_by_index(i)['name']) for i in range(p.get_device_count())]"
```
Mettre l'index trouvé dans `MIC_INDEX` dans `config.py`. Si le micro lève `[Errno -9999]`, essayer un autre index.

**Webcam inaccessible :**
L'erreur `can't grab frame (-1072875772)` signifie que la caméra est utilisée par une autre application (Teams, navigateur, OBS…). Fermer ces applications avant de lancer SMILE.

**Tester la voix TTS :**
```bat
facenet\Scripts\python.exe -c "import pyttsx3; e=pyttsx3.init(); e.say('Bonjour, je suis SMILE'); e.runAndWait()"
```

**Tester la connexion Furhat :**
```bat
facenet\Scripts\python.exe -c "from furhat_remote_api import FurhatRemoteAPI; f=FurhatRemoteAPI('localhost'); f.say(text='Bonjour, je suis SMILE')"
```
Si ça échoue (`ConnectionError`), vérifier que le Virtual Furhat est bien lancé (SDK Launcher) et que `http://localhost:8080` répond. Le code bascule alors automatiquement sur `pyttsx3`, donc l'absence de Furhat n'empêche pas SMILE de fonctionner — juste la voix/les gestes seront dégradés.

---

## Portage Linux (référence)

Le code utilise `msvcrt` pour écouter la touche `q` — ce module est **Windows uniquement**. Pour Linux, remplacer dans `src/recognize_live.py` :

```python
# Remplacer : import msvcrt et la fonction key_listener basée sur msvcrt
# Par :
import sys, select

def key_listener():
    while not exit_event.is_set():
        if select.select([sys.stdin], [], [], 0.1)[0]:
            if sys.stdin.read(1).lower() == 'q':
                exit_event.set()
                break
```

Sur Linux, utiliser `.venv/bin/activate` et `python3` à la place de `facenet\Scripts\activate` et `python`.
