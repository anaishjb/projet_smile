# Guide d'installation et d'utilisation — SMILE

**SMILE** (Social Memory Integrated Learning Environment) est un agent conversationnel embarqué qui :
- reconnaît les visages en temps réel (MTCNN + FaceNet),
- transcrit la parole hors ligne en français (Vosk STT),
- génère des réponses via un LLM local (Ollama/llama3:8b),
- mémorise chaque utilisateur entre les sessions (profils JSON + résumés LLM).

---

## Lancer SMILE (utilisation courante)

Ouvre deux terminaux :

**Terminal 1 — Ollama (LLM local) :**
```bat
ollama serve
```

**Terminal 2 — SMILE :**
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

### 4. Créer le fichier de configuration

```bat
copy src\config_example.py src\config.py
```

Éditer `src\config.py` :

```python
BASE_DIR = "C:/Users/LUTIN/Documents/Projets/SMILE/SMILE"  # ← adapter
VOSK_MODEL_PATH = "C:/Users/LUTIN/models/vosk-model-fr-0.22/vosk-model-fr-0.22"  # ← adapter
MIC_INDEX = 20        # ← index de ton micro (voir section Dépannage)
EMBEDDINGS_FILE = f"{BASE_DIR}/data/embeddings.pkl"  # (renommer depuis EMBEDDINGS_PATH dans l'exemple)
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
