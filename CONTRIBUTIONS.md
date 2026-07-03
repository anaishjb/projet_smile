# Contributions au projet SMILE


## 1. Adaptation linguistique

- Traduction des prompts LLM en français (`dialog_manager.py`)
- Adaptation des expressions régulières de reconnaissance du prénom aux formulations françaises (`je m'appelle`, `c'est`)
- Traduction des mots-clés de salutation et d'au revoir
- Ajout de règles de communication adaptées au public vulnérable (personnes âgées, troubles cognitifs) : vocabulaire simple, phrases courtes, pas de correction, pas d'hypothèses émotionnelles, 2 phrases maximum par réponse

## 2. Gestion des identifiants visages

- Remplacement du prénom brut par un `face_id` unique horodaté (`prenom_AAAAMMJJ_HHMMSS`) via `generate_face_id()`
- Séparation entre `face_id` (identifiant technique) et `display_name` (prénom affiché)

## 3. Intégration de Furhat

- Ajout du singleton `get_furhat()` dans `speech_utils.py` avec fallback automatique sur pyttsx3 si Furhat n'est pas disponible
- Intégration de la synthèse vocale Azure TTS via Furhat Remote API

## 4. Gestes Furhat

- **Geste de réflexion** (`GazeAway + BrowRaise`) : déclenché avant chaque appel au LLM dans les 3 états (GREETING, FAREWELL, FREE_TALK) pour masquer visuellement la latence
- **Signal de tour de parole** (`Nod`) : déclenché après chaque réponse en FREE_TALK pour indiquer à l'utilisateur qu'il peut parler
- **Nod après salutation initiale** : déclenché après le "Bonjour" initial pour signaler le début de la prise de parole

## 5. Préchauffage Ollama

- Ajout d'un mécanisme de préchauffage dans `start_executors()` (`async_core.py`) : une requête HTTP minimale (`num_predict: 1`) est envoyée à Ollama au démarrage pour charger le modèle en RAM avant le premier utilisateur, évitant ainsi les TimeoutError



## 6. Robustesse

- Sauvegarde du profil utilisateur garantie même en cas d'échec du LLM lors du résumé (`summarize_conversation`)
- Tous les appels Furhat encadrés d'un `try/except` pour ne pas bloquer SMILE si Furhat est absent
- Préchauffage Ollama non-bloquant en cas d'indisponibilité du service



