# Journal des modifications — SMILE

---

## Session du 2026-06-22

### 1. Bug : profil jamais créé malgré une conversation enregistrée

**Problème** : Alice avait un fichier `data/conversations/Alice.json` mais aucun `data/profiles/Alice.json`.

**Cause** : `save_profile()` n'était appelé qu'à l'intérieur de `summarize_conversation()`, elle-même entièrement enveloppée dans un `try/except`. Si Ollama échouait ou renvoyait un JSON invalide, l'exception était silencieusement capturée et `save_profile()` n'était jamais exécuté.

**Corrections** :

- **`src/recognize_live.py`** : après `save_new_face()`, le profil est maintenant créé immédiatement dès que le nom de l'utilisateur est obtenu.
- **`src/utils/dialog_manager.py`** : `summarize_conversation()` restructurée — le bloc LLM est dans le `try/except`, mais `save_profile()` est en dehors et s'exécute toujours, même si le LLM échoue.

---

### 2. Refactor : collisions de prénoms → système face_id

**Problème** : deux utilisateurs portant le même prénom (ex. deux "Alice") écrasaient mutuellement leurs embeddings, profils et historiques de conversation.

**Cause racine** : le prénom était utilisé comme clé primaire unique dans toute la chaîne de stockage (`embeddings.pkl`, `profiles/<name>.json`, `conversations/<name>.json`).

**Solution** : introduction d'un `face_id` unique généré à la création de chaque utilisateur, de la forme `prenom_YYYYMMDD_HHMMSS` (ex. `alice_20260622_143052`). Le prénom reste un attribut d'affichage stocké dans le profil JSON (`"name"`), mais n'est plus la clé de stockage.

**Fichiers modifiés** :

| Fichier | Modifications |
|---|---|
| `src/recognize_live.py` | Ajout de `generate_face_id()`. `handle_interaction()` reçoit `face_id` + `display_name` séparément. `seen_faces` utilise `face_id` comme clé. Correction bonus : `seen_faces[face_id]` mis à jour depuis le thread d'interaction pour éviter le re-déclenchement après enregistrement d'un nouvel utilisateur. |
| `src/utils/memory_manager.py` | `save_new_face(face_id, embedding)` et `log_full_conversation(face_id, ...)` — les fichiers sont nommés d'après le `face_id`. |
| `src/utils/profile_manager.py` | `load_profile(face_id)` — le profil par défaut contient les deux champs `"face_id"` et `"name"`. Suppression de la duplication de code via `_default_profile()`. |
| `src/utils/dialog_manager.py` | `build_llm_prompt(face_id, ...)` charge le profil par `face_id` et utilise `profile["name"]` pour construire le prompt (nom affiché, pas la clé de stockage). `ask_ollama_with_context()` et `summarize_conversation()` mis à jour en conséquence. |

**Migration des données** : les fichiers `data/embeddings.pkl`, `data/conversations/*.json` et `data/profiles/*.json` existants (ancien format, clés = prénoms) ont été supprimés. Les utilisateurs seront réenregistrés au prochain lancement.

---

### 3. Suppression des emojis du code

Tous les emojis présents dans les messages de log et les commentaires ont été retirés des fichiers sources et remplacés par des préfixes texte (`[SYS]`, `[CONV]`, `[TRACK]`, `[TTS]`, `[MIC]`, `[STT]`, `[DETECT]`, `[EMBED]`, `[CORE]`).

**Fichiers modifiés** : `src/recognize_live.py`, `src/utils/async_core.py`, `src/utils/speech_utils.py`.

---

### 4. Amélioration des prompts LLM — public vulnérable

**Fichier modifié** : `src/utils/dialog_manager.py`

**`build_llm_prompt`** : ajout d'une section `RÈGLES IMPORTANTES — PUBLIC VULNÉRABLE` adaptée au contexte de SMILE (personnes âgées ou avec troubles cognitifs) :
- Être patient et bienveillant en toutes circonstances, même si l'utilisateur se répète.
- Utiliser des phrases courtes, un vocabulaire simple et concret ; éviter les métaphores et le langage abstrait.
- Ne jamais corriger l'utilisateur.
- Ne jamais faire d'hypothèses sur l'état émotionnel de l'utilisateur s'il ne l'a pas exprimé clairement.

**`summarize_conversation`** : ajout de l'instruction *"Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ni après, sans balises markdown"* pour éviter les erreurs de parsing lorsque le LLM enveloppe sa réponse dans des blocs de code.
