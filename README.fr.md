# scheduler

[中文](README.zh-CN.md) · [English](README.md) · [Français](README.fr.md)

Un petit paquet Python pour les exécutions séquentielles sans surveillance. Le harness fournit un plan JSON et une consigne de révision, lance le scheduler, puis peut se mettre en pause. Le scheduler poursuit son travail indépendamment de la conversation.

Exécuter serial i → lire les résultats → demander à l’API si un changement est nécessaire → conserver le plan ou modifier les valeurs command/task en attente → lancer la tâche suivante. Une liste `updates` vide signifie continuer sans modification. Aucun appel API n’est effectué après la dernière tâche.

Compatible avec macOS/Linux et Python 3.10+. À l’exécution, seule la bibliothèque standard est nécessaire. Gardez la machine éveillée. Ce paquet ne relance pas une conversation Codex : si une tâche exige des modifications de code, le harness doit prévoir une commande ou un outil CLI capable de les réaliser.

## Installation et configuration INI

```bash
git clone https://github.com/ShimingGu/scheduler.git
cd scheduler
python3 -m pip install -e .
```

Si le paquet se trouve dans le dossier `./scheduler` d’un autre projet, exécutez `python3 -m pip install -e ./scheduler` depuis ce projet. Après installation, `python3 -m scheduler` et `serial-scheduler` fonctionnent depuis n’importe quel répertoire. Aucune interface graphique n’est nécessaire.

Copiez et modifiez [examples/scheduler.ini](examples/scheduler.ini) :

```ini
[scheduler]
plan = plan.json
run_dir = runs/night-001
autonomy = faithful

[api]
key_file = /absolute/path/to/your/api-key.env
base_url = https://api.deepseek.com/v1
model = deepseek-flash
reasoning_effort = default
timeout = 120
max_tokens = 4096
```

Les chemins relatifs de l’INI sont résolus depuis le **dossier de l’INI** ; les chemins cwd et key_file relatifs d’un plan le sont depuis le **dossier du plan**. Les arguments CLI explicites plan/run-dir priment sur l’INI ; les réglages API et autonomy de l’INI priment sur le plan. Chaque champ endpoint/model absent de la configuration explicite est lu, si disponible, dans le fichier de clé sélectionné. L’analyse de la configuration n’exécute jamais de code shell et ne développe pas les expressions de variables d’environnement.

Le fichier de clé peut être au format `.env` (`OPENAI_API_KEY`, `SCHEDULER_API_KEY`, `HF_TOKEN`, `DEEPSEEK_API_KEY`), JSON (`api_key`, avec `base_url`/`model` facultatifs), ou contenir une clé en texte brut. L’INI accepte une référence de fichier, pas la clé elle-même. Vous pouvez aussi remplacer `key_file` par `key_env = MY_API_KEY` et fournir les identifiants par l’environnement. Excluez les véritables identifiants et les résultats d’exécution du contrôle de version.

```bash
# Lancer en arrière-plan ; renvoie immédiatement un JSON : pid / run_dir / log / plan
python3 -m scheduler start --config /absolute/path/to/scheduler.ini

# Consulter l’état au format JSON
python3 -m scheduler status --config /absolute/path/to/scheduler.ini

# Lister les modèles et les niveaux de raisonnement déclarés au format JSON
python3 -m scheduler models --config /absolute/path/to/scheduler.ini

# Exécuter au premier plan jusqu’à la fin ; code de sortie non nul en cas d’échec
python3 -m scheduler run --config /absolute/path/to/scheduler.ini
```

`start` enregistre la configuration effective sans valeur de clé et renvoie son chemin dans le champ `plan`. Le processus lit cet instantané afin de conserver les réglages de l’INI après le détachement. Les fichiers de clés doivent rester lisibles ; les identifiants d’environnement sont hérités au lancement. La syntaxe initiale `run/start plan.json --run-dir ...` reste disponible.

## Appel direct par le harness

Le harness écrit le plan JSON et l’INI, puis appelle `start` une seule fois, sans saisie interactive. Il peut ensuite se mettre en pause :

```python
import json
import subprocess
import sys

launched = subprocess.run(
    [sys.executable, "-m", "scheduler", "start", "--config", "/path/to/scheduler.ini"],
    check=True, capture_output=True, text=True,
)
worker = json.loads(launched.stdout)
# Contient pid, run_dir, log et plan ; le scheduler poursuit son travail seul.
```

Le succès de `start` signifie qu’un processus d’arrière-plan a été créé, pas que le plan est terminé. Consultez `status`, state.json et les journaux pour suivre l’avancement. Utilisez un run_dir distinct pour chaque exécution indépendante. Un échec au lancement produit un code de sortie non nul et une erreur JSON sur stderr, sans demande de saisie ni de confirmation.

## Clusters / Slurm

Installez le paquet sur le nœud de calcul, rendez le fichier de clé accessible et vérifiez que le nœud peut joindre l’API configurée. Utilisez **`run` au premier plan** dans l’allocation pour que le job couvre toute la durée du traitement :

```bash
sbatch examples/slurm.sh /absolute/path/to/scheduler.ini
```

[examples/slurm.sh](examples/slurm.sh) est un modèle minimal ; ajoutez les paramètres partition/account requis par votre cluster. Ne remplacez pas son `run` au premier plan par `start` avant de quitter immédiatement le job. Les autres systèmes de gestion de jobs peuvent invoquer la même commande `run --config ...`.

## Autonomie et effort de raisonnement

| autonomy | Politique de décision |
| --- | --- |
| `faithful` | Appliquer la modification minimale exigée par les règles explicites ; sinon continuer. Valeur par défaut. |
| `mediocre` | Déduire les corrections courantes nécessaires et les détails d’exécution ; éviter les optimisations spéculatives. |
| `ingenious` | Améliorer activement la suite du plan à partir des résultats, dans les objectifs et limites du harness. |

Tous les modes privilégient un plan existant qui fonctionne. Ils orientent le jugement du modèle ; ils ne constituent pas une isolation des permissions du système.

`reasoning_effort` règle séparément le raisonnement du modèle. Avec `default`, le paramètre est omis pour assurer la compatibilité. Les autres valeurs nécessitent la prise en charge du modèle et ne sont jamais supprimées silencieusement après un refus du fournisseur. `models` affiche les niveaux déclarés, ou seulement default en l’absence de métadonnées. La présence d’un modèle dans la liste ne garantit ni l’accès ni un solde suffisant pour la clé choisie. Voir les [métadonnées DeepSeek](https://api-docs.deepseek.com/api/list-models/), les [paramètres de raisonnement](https://api-docs.deepseek.com/api/create-chat-completion/) et les [paramètres Hugging Face](https://huggingface.co/docs/inference-providers/en/tasks/chat-completion).

## Interface graphique locale facultative

```bash
python3 -m scheduler ui --port 8765
```

Ouvrez `http://127.0.0.1:8765/`. Le sélecteur en haut à droite propose **中文 / English / Français**. L’interface mémorise votre choix et traduit les libellés, notifications, erreurs et états. Le changement de langue conserve les clés, les modèles sélectionnés et les plans modifiés ; les consignes d’origine, données des tâches et identifiants du protocole restent intacts.

Importez les fichiers de clés, choisissez le modèle, l’effort et l’autonomie, importez un plan, puis lancez l’exécution en arrière-plan. L’interface n’écoute que sur l’adresse de bouclage et vérifie un jeton de session. Les clés importées restent en mémoire et sont transmises aux processus par variables d’environnement, pas par les plans. Réimportez-les après un redémarrage de l’interface. Fermer la page ou le service d’interface n’arrête pas les processus déjà lancés. Le cwd des plans de l’interface doit être absolu. `--run-root` permet de choisir le dossier des enregistrements.

## Informations à fournir par le harness

Voir [examples/plan.json](examples/plan.json).

- `cwd` : répertoire de travail des commandes ; le CLI résout les chemins relatifs depuis le dossier du plan.
- `api` : `base_url` (par exemple `https://api.deepseek.com/v1` ou `https://router.huggingface.co/v1`), `model`, `key_env` (par défaut `SCHEDULER_API_KEY`), et éventuellement `key_file`, `reasoning_effort`, `timeout` en secondes et `max_tokens`. Seuls les fichiers de clés explicitement choisis sont lus ; aucun fichier privé n’est recherché automatiquement.
- `steps` : liste ordonnée de tâches avec un `id` unique, une `command` sous forme de tableau d’arguments et un objet JSON `task` facultatif. Les commandes sont exécutées directement, sans shell.
- `revision_prompt` : consigne **rédigée par le harness**, précisant les déclencheurs, modifications autorisées et contraintes. Privilégiez le plan initial ; évitez les formulations vagues comme « améliorer les tâches suivantes ». Chaque requête API contient cette consigne, le dernier résultat et toutes les tâches en attente.
- `step_timeout` : durée maximale d’une commande en secondes ; valeur par défaut 86400.

Exemple : « Augmenter samples de la prochaine tâche uniquement si recommended_samples du pilote est supérieur. Conserver les autres réglages et commandes. Sinon renvoyer une liste updates vide. »

Une tâche lit sa configuration finale dans `SCHEDULER_TASK_FILE` et écrit son résultat JSON dans `SCHEDULER_RESULT_FILE` ; voir [examples/worker.py](examples/worker.py). Le scheduler lit après la fin de la commande, une écriture ordinaire suffit donc. Les résultats sont limités à 100 Ko : rédigez un résumé et indiquez les chemins des données complètes. Sans résultat JSON, l’API reçoit les 12 derniers Ko de stdout et de stderr ; les journaux complets restent sur disque.

Le modèle renvoie :

```json
{"reason": "Aucun ajustement nécessaire", "updates": []}
```

Ou :

```json
{"reason": "Le pilote exige davantage d’échantillons", "updates": [{"id": "main", "task": {"samples": 40}}]}
```

`task` et `command` sont remplacés intégralement, sans fusion partielle. Les champs et tâches non mentionnés restent inchangés. Plusieurs tâches en attente peuvent être modifiées ; il est interdit d’ajouter, supprimer, réordonner ou modifier des tâches terminées. Le modèle renvoie du JSON, pas du texte exécuté directement. Il ne peut pas lire lui-même des fichiers arbitraires. Les commandes disposent des permissions de l’utilisateur courant : définissez le périmètre autorisé dans la consigne. Les sorties sont envoyées à l’API choisie ; ne mettez pas d’identifiants dans les résumés et journaux.

## Reprendre un serial i déjà en cours

Placez uniquement les tâches non démarrées dans `steps`, puis ajoutez :

```json
"handoff": {
  "id": "serial-i",
  "completion_file": "/absolute/path/unique-run/completion.json",
  "timeout": 86400,
  "poll_interval": 1
}
```

La tâche en cours ou son script d’encapsulation doit **publier ce fichier de façon atomique après le succès** :

```json
{"status": "completed", "result": {"metric": 0.82, "summary": "Résumé du résultat de la tâche en cours"}}
```

Utilisez `scheduler.core.write_json` pour la publication atomique. Le chemin doit être propre à cette exécution et absent au départ. Le scheduler attend le fichier, lit le résultat, évalue les tâches en attente puis lance la suivante. En cas d’échec, publiez `status: "failed"` pour l’arrêter. Le script initial ne doit pas lancer lui aussi les tâches suivantes : leur exécution est confiée au scheduler. Un simple PID ne suffit pas à déterminer le succès ou à recueillir les résultats ; la reprise utilise donc un fichier de fin explicite.

## État et reprise après incident

Le dossier d’exécution contient `state.json`, les configurations, résultats et journaux de chaque tâche, ainsi que les décisions de l’API. Un seul scheduler peut le gérer à la fois. Ne modifiez pas le plan initial pendant l’exécution ; les révisions sont conservées dans l’état.

Une erreur API ou une mise à jour invalide suspend le traitement à l’état `revising`, avant la commande suivante. Corrigez les identifiants ou le réseau, puis rappelez `run` avec le même plan effectif et dossier d’exécution pour réessayer la décision sans relancer les commandes terminées. Un délai d’attente dépassé pour un fichier de fin peut aussi être réessayé.

Un échec ou dépassement de délai d’une commande, ou l’arrêt du scheduler pendant son exécution, exige une vérification manuelle. Le scheduler ne devine jamais si des effets de bord se sont produits avant de rejouer une commande. Après vérification, créez un nouveau plan et un nouveau dossier pour le travail restant. `status` affiche le dernier point de contrôle, pas un signal de vie : un processus tué peut encore apparaître comme `running`. Consultez son PID et ses journaux.

## Vérification

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Les tests automatisés utilisent des tâches temporaires, des API simulées et des clés synthétiques, sans identifiants utilisateur. Un test réel a également confirmé qu’une recommandation de 40 du pilote modifiait main.samples de 20 à 40 et que la tâche suivante utilisait bien 40. Les identifiants et enregistrements des tests en ligne sont exclus du dépôt.
