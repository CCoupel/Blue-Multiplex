#!/usr/bin/env bash
# Identité persistante des adaptateurs Bluetooth de btmux (#18) : pour chaque entrée de `adapters[]`, retrouve l'index
# `hciN` par la MAC (jamais d'index en dur, pas de règle udev), fixe l'alias (persistant, stocké par BlueZ) et la classe
# d'appareil selon le rôle, et ferme découverte et appairage (c'est btmuxd qui ouvre les fenêtres, #20).
# Tout autre contrôleur présent (sans rôle : Bluetooth interne, dongle non affecté — #23) est seulement fermé
# (bondable off, discov no) : ni alias ni classe ne sont touchés.
#   - rôle `sources`  -> classe « casque audio » (majeur 4 / mineur 4 ; la classe finale 0x240404 dépend des UUIDs) ;
#   - rôle `headsets` seul -> classe « ordinateur » (majeur 1 / mineur 12 = portable).
# Usage : btmux-adapters.sh [--config /etc/btmux/config.yaml] [--state FICHIER] [--dry-run] [--wait SECONDES] [--reset]
#                          [--only MAC]... [--requests FICHIER]
#   --state   : fichier d'état des rôles (#23, ex. /var/lib/btmux/adapters.yaml) ; s'il existe et est valide, sa liste
#               prime sur celle de la config (transmis à `btmux.config adapters --state`). Absent : défaut de btmux.config.
#   --dry-run : affiche les commandes sans rien modifier (utilisable sans droits root).
#   --reset   : ne fait que refermer appairage et découverte (bondable off, discov no) de tous les contrôleurs
#               présents — ExecStopPost de btmuxd.
#   --wait N  : attend jusqu'à N s (défaut 20) que tous les adaptateurs de la config soient énumérés (USB).
#   --only MAC: ne traite que ce contrôleur (#23 hotplug) : identité s'il est affecté, sinon simple fermeture ; aucun autre
#               contrôleur n'est touché (une fenêtre d'appairage ouverte ailleurs reste ouverte). Répétable (MAC dédoublonnées,
#               casse indifférente). MAC vide ou invalide : ignorée avec avertissement (contenu jamais reproduit) ; aucune MAC
#               valide, ou MAC absente après --wait : avertissement, code 0 (btmux-adapters-identity.service ne doit jamais
#               échouer).
#   --requests F: lit les MAC à traiter dans F (/var/lib/btmux/identity.request, une ligne « ISO<TAB>hciN<TAB>MAC » par
#               contrôleur en attente ; la MAC du 3e champ fait foi) et les ajoute comme autant de --only. F doit être un
#               fichier régulier : lien symbolique ou autre type -> ignoré, avertissement. Lignes invalides ignorées
#               (« N ligne(s) invalide(s) », contenu jamais reproduit). Lecture bornée (4 Kio). Rien de valide : code 0.
#               En fin de passe, F est relu : les MAC apparues pendant la passe (absentes de toutes les passes précédentes)
#               font l'objet d'une passe complémentaire limitée à ces MAC, au plus BTMUX_REQUESTS_REREAD fois (défaut 3) —
#               jamais de boucle. Les MAC déjà traitées et encore en attente d'acquittement par btmuxd sont ignorées.
# Idempotent. Sans adaptateur présent : avertissement et code 0 (ne bloque jamais le démarrage). Config invalide : code 2.
# Variables : BTMUX_PYTHON (défaut /opt/btmux/bin/python, repli python3), BTMUX_BTMGMT, BTMUX_BUSCTL,
#   BTMUX_CLASS_SOURCES (« 4 4 »), BTMUX_CLASS_HEADSETS (« 1 12 »), BTMUX_ALIAS_WAIT (« 5 » : attente max., en s, que
#   BlueZ expose /org/bluez/hciN avant de poser l'alias), BTMUX_TRIGGER (unité appelante, journalisée : boot, btmuxd, hotplug),
#   BTMUX_REQUESTS_REREAD (« 3 » : nombre max. de relectures de --requests en fin de passe).
set -euo pipefail

CONFIG=/etc/btmux/config.yaml STATE="" DRY=0 WAIT=20 RESET=0 ONLY="" ONLY_SET=0 REQUESTS=""
MAC_RE='^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$'
add_only() {   # MAC -> ajoutée à ONLY (« MAC1 MAC2 », majuscules, dédoublonnée) ; code 1 si invalide
  [[ "$1" =~ $MAC_RE ]] || return 1
  case " $ONLY " in *" ${1^^} "*) ;; *) ONLY="${ONLY:+$ONLY }${1^^}" ;; esac
}
# Requêtes de hotplug (#23) : le répertoire appartient à l'utilisateur de service, la lecture est faite par root. On refuse
# tout ce qui n'est pas un fichier régulier, puis on exige que le chemin canonique soit identique au chemin donné (aucun
# lien, ni sur le fichier ni sur un répertoire parent) et que le descripteur ouvert désigne ce fichier. Un lien substitué
# après cette vérification n'est pas détecté (résiduel accepté : le répertoire appartient au compte de service déjà
# privilégié sur le daemon, et seules des MAC valides sont exploitables). Jamais de contenu rejeté dans le journal.
read_requests() {   # FICHIER [quiet] -> MAC ajoutées à ONLY ; quiet : ne recompte pas les lignes invalides (relecture)
  local f="$1" quiet="${2:-}" mac bad=0 real opened
  notreg() { echo "btmux-adapters: AVERTISSEMENT $f n'est pas un fichier régulier (lien symbolique ou autre) — ignoré" >&2; }
  if [ -L "$f" ] || { [ -e "$f" ] && [ ! -f "$f" ]; }; then notreg; return 0; fi
  [ -e "$f" ] || return 0   # absent : rien à faire (avertissement global plus bas)
  exec 3< "$f" || { echo "btmux-adapters: AVERTISSEMENT $f illisible — ignoré" >&2; return 0; }
  if [ -e /proc/self/fd/3 ]; then
    real="$(readlink -f -- "$f" 2>/dev/null || true)"
    opened="$(readlink /proc/self/fd/3 2>/dev/null || true)"
    if [ -z "$real" ] || [ "$real" != "$f" ] || [ "$opened" != "$real" ] || [ ! -f /proc/self/fd/3 ]; then
      exec 3<&-; notreg; return 0
    fi
  fi
  while IFS=$'\t' read -r _ _ mac _; do
    mac="${mac%$'\r'}"
    add_only "$mac" || bad=$((bad + 1))
  done < <(head -c 4096 <&3 | grep -v '^[[:space:]]*$' || true)
  exec 3<&-
  [ "$bad" -eq 0 ] || [ -n "$quiet" ] || echo "btmux-adapters: AVERTISSEMENT $f : $bad ligne(s) invalide(s) ignorée(s) (MAC invalide)" >&2
}
while [ $# -gt 0 ]; do
  case "$1" in
    --config) CONFIG="${2:?chemin}"; shift 2 ;;
    --state) STATE="${2:?chemin}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --reset) RESET=1; shift ;;
    --wait) WAIT="${2:?secondes}"; shift 2 ;;
    --only)
      [ $# -ge 2 ] || { echo "btmux-adapters: --only attend une MAC" >&2; exit 2; }
      ONLY_SET=1
      add_only "$2" || echo "btmux-adapters: AVERTISSEMENT --only : MAC vide ou invalide — ignorée" >&2
      shift 2 ;;
    --requests) REQUESTS="${2:?chemin}"; ONLY_SET=1; shift 2 ;;
    -h|--help) sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "btmux-adapters: option inconnue: $1" >&2; exit 2 ;;
  esac
done
[[ "$WAIT" =~ ^[0-9]+$ ]] || { echo "btmux-adapters: --wait attend un entier" >&2; exit 2; }
[ -z "$REQUESTS" ] || read_requests "$REQUESTS"
if [ "$ONLY_SET" = 1 ] && [ -z "$ONLY" ]; then
  echo "btmux-adapters: AVERTISSEMENT aucune MAC valide à traiter (MAC vide ou invalide) — rien à faire" >&2
  exit 0
fi
is_only() { case " $ONLY " in *" $1 "*) return 0 ;; esac; return 1; }   # MAC (majuscules) ciblée par --only ?

PY="${BTMUX_PYTHON:-/opt/btmux/bin/python}"
[ -x "$PY" ] || PY=python3
BTMGMT="${BTMUX_BTMGMT:-btmgmt}"
BUSCTL="${BTMUX_BUSCTL:-busctl}"
CLASS_SOURCES="${BTMUX_CLASS_SOURCES:-4 4}"
CLASS_HEADSETS="${BTMUX_CLASS_HEADSETS:-1 12}"
ALIAS_WAIT="${BTMUX_ALIAS_WAIT:-5}"
[[ "$ALIAS_WAIT" =~ ^[0-9]+$ ]] || { echo "btmux-adapters: BTMUX_ALIAS_WAIT attend un entier" >&2; exit 2; }
TRIGGER="${BTMUX_TRIGGER:-manuel}"
REREAD_MAX="${BTMUX_REQUESTS_REREAD:-3}"
[[ "$REREAD_MAX" =~ ^[0-9]+$ ]] || { echo "btmux-adapters: BTMUX_REQUESTS_REREAD attend un entier" >&2; exit 2; }
SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo -n"

log() { echo "btmux-adapters: $*"; }
FAILED=0
run() {
  if [ "$DRY" = 1 ]; then echo "DRY-RUN: $*"; elif ! "$@"; then FAILED=1; echo "btmux-adapters: AVERTISSEMENT commande en échec: $*" >&2; fi
}
# btmgmt se bloque quand stdin est /dev/null (contexte systemd) : on lui donne un tube fermé après une ligne, et un plafond.
# shellcheck disable=SC2086
mgmt() { printf '\n' | timeout 10 $SUDO $BTMGMT "$@"; }

rc=0
ARGS=(adapters --config "$CONFIG")
[ -z "$STATE" ] || ARGS+=(--state "$STATE")
FULL_LIST="$("$PY" -I -P -m btmux.config "${ARGS[@]}")" || rc=$?
if [ "$rc" -ne 0 ]; then
  if [ "$rc" -eq 2 ]; then
    echo "btmux-adapters: configuration invalide ($CONFIG${STATE:+, état $STATE})" >&2
  else
    echo "btmux-adapters: impossible d'exécuter 'btmux.config' avec $PY (code $rc) — venv /opt/btmux absent ou btmux non installé ? (BTMUX_PYTHON)" >&2
  fi
  exit 2
fi

MGMT_ERR=0
index_of() {   # MAC -> index hciN (vide si absent ou si btmgmt échoue : MGMT_ERR=1)
  local out
  if ! out="$(mgmt info 2>/dev/null)"; then MGMT_ERR=1; return 0; fi
  printf '%s\n' "$out" | awk -v mac="$1" '
    /^hci[0-9]+:/ { idx = substr($1, 4); sub(/:$/, "", idx) }
    tolower($1) == "addr" && toupper($2) == toupper(mac) { print idx; exit }'
}

all_indices() {   # tous les contrôleurs présents : une ligne « index<TAB>MAC » (vide si btmgmt échoue)
  local out
  out="$(mgmt info 2>/dev/null)" || return 0
  printf '%s\n' "$out" | awk '
    /^hci[0-9]+:/ { idx = substr($1, 4); sub(/:$/, "", idx) }
    tolower($1) == "addr" && idx != "" { print idx "\t" toupper($2); idx = "" }'
}

# Alias : l'objet D-Bus /org/bluez/hciN peut apparaître après l'index mgmt (hotplug, redémarrage de bluetoothd) ; on attend
# jusqu'à ALIAS_WAIT s (pas de 0,5 s) qu'il réponde. Lecture seule : pas de sudo (propriété lisible par tous sur le bus système).
alias_of() {   # index -> alias courant ; code 1 si l'objet ne répond pas
  local out
  out="$($BUSCTL get-property org.bluez "/org/bluez/hci$1" org.bluez.Adapter1 Alias 2>/dev/null)" || return 1
  printf '%s\n' "$out" | sed -n 's/^s "\(.*\)"$/\1/p'
}
wait_alias() {   # index -> alias courant (code 1 après ALIAS_WAIT s sans réponse)
  local tries=$((ALIAS_WAIT * 2))
  while :; do
    alias_of "$1" && return 0
    [ "$tries" -gt 0 ] || return 1
    tries=$((tries - 1))
    sleep 0.5
  done
}

# btmgmt inutilisable (absent, sudo refusé, socket mgmt) : message explicite, code 0 (contrat : ne bloque pas le démarrage)
index_of 00:00:00:00:00:00 >/dev/null
if [ "$MGMT_ERR" = 1 ] && [ "$DRY" != 1 ]; then
  echo "btmux-adapters: AVERTISSEMENT '$BTMGMT info' a échoué (absent, droits ou socket mgmt) — aucun adaptateur configurable" >&2
  exit 0
fi

# Une passe sur ONLY (vide : tous les contrôleurs). Rejouée en fin de passe pour les requêtes arrivées entre-temps (#23).
identity_pass() {
  local LIST deadline missing mac name roles idx class current ASSIGNED SEEN SCOPE
  # Une ligne par passe : preuve QA du déclencheur (btmux-adapters.service, ExecStartPre/ExecStopPost de btmuxd, hotplug #23).
  case "$ONLY" in
    "") SCOPE="" ;;
    *" "*) SCOPE=", contrôleurs ${ONLY// /, } seuls" ;;
    *) SCOPE=", contrôleur $ONLY seul" ;;
  esac
  if [ "$RESET" = 1 ]; then log "passe fermeture (déclencheur : $TRIGGER$SCOPE)"; else log "passe identité (déclencheur : $TRIGGER$SCOPE)"; fi
  # --only : la liste effective est réduite aux entrées de ces MAC (vide si aucun n'a de rôle).
  LIST="$FULL_LIST"
  if [ -n "$ONLY" ]; then
    LIST="$(printf '%s\n' "$FULL_LIST" | awk -F '\t' -v macs="$ONLY" '
      BEGIN { n = split(macs, m, " "); for (i = 1; i <= n; i++) want[m[i]] = 1 }
      toupper($1) in want')"
  fi
  deadline=$((SECONDS + WAIT))
  while :; do
    missing=0
    while IFS=$'\t' read -r mac _ _; do
      [ -n "$mac" ] || continue
      [ -n "$(index_of "$mac")" ] || missing=1
    done <<< "$LIST"
    # --only d'une MAC non affectée : on attend quand même son énumération.
    for mac in $ONLY; do [ -n "$(index_of "$mac")" ] || missing=1; done
    { [ "$missing" = 0 ] || [ "$DRY" = 1 ] || [ "$SECONDS" -ge "$deadline" ]; } && break
    sleep 1
  done

  ASSIGNED=" "   # index des contrôleurs listés (affectés à un rôle), séparés par des espaces
  while IFS=$'\t' read -r mac name roles; do
    [ -n "$mac" ] || continue
    idx="$(index_of "$mac")"
    if [ -z "$idx" ]; then
      echo "btmux-adapters: AVERTISSEMENT adaptateur $mac ($name, rôles $roles) introuvable — ignoré" >&2
      [ "$DRY" = 1 ] && echo "DRY-RUN: (adaptateur $mac absent : aucune commande n'est planifiée)"
      continue
    fi
    ASSIGNED="$ASSIGNED$idx "
    if [ "$RESET" = 1 ]; then
      log "$mac -> hci$idx fermeture de l'appairage et de la découverte"
      run mgmt -i "$idx" bondable off
      run mgmt -i "$idx" discov no
      continue
    fi
    case ",$roles," in
      *,sources,*) class="$CLASS_SOURCES" ;;
      *) class="$CLASS_HEADSETS" ;;
    esac
    log "$mac -> hci$idx rôles=$roles alias='$name' classe='$class'"
    # shellcheck disable=SC2086
    {
      run mgmt -i "$idx" power on
      if [ "$DRY" = 1 ]; then
        run $SUDO $BUSCTL set-property org.bluez "/org/bluez/hci$idx" org.bluez.Adapter1 Alias s "$name"
      elif ! current="$(wait_alias "$idx")"; then
        # Classe et fermeture (btmgmt) restent appliquées ; l'alias le sera à la prochaine passe.
        echo "btmux-adapters: AVERTISSEMENT /org/bluez/hci$idx absent du bus après ${ALIAS_WAIT} s — alias '$name' non appliqué" >&2
      elif [ "$current" != "$name" ]; then
        run $SUDO $BUSCTL set-property org.bluez "/org/bluez/hci$idx" org.bluez.Adapter1 Alias s "$name"
      fi
      run mgmt -i "$idx" class $class
      run mgmt -i "$idx" bondable off
      run mgmt -i "$idx" discov no
    }
  done <<< "$LIST"

  # Contrôleurs sans rôle (#23) : fermés, classe et alias intacts (--only : ces contrôleurs seulement).
  SEEN=" "
  while IFS=$'\t' read -r idx mac; do
    [ -n "$idx" ] || continue
    [ -z "$ONLY" ] || is_only "$mac" || continue
    SEEN="$SEEN$mac "
    case "$ASSIGNED" in *" $idx "*) continue ;; esac
    log "$mac -> hci$idx sans rôle : fermeture de l'appairage et de la découverte"
    run mgmt -i "$idx" bondable off
    run mgmt -i "$idx" discov no
  done <<< "$(all_indices)"
  if [ "$DRY" != 1 ]; then
    for mac in $ONLY; do
      case "$SEEN" in *" $mac "*) ;; *) echo "btmux-adapters: AVERTISSEMENT contrôleur $mac absent — rien à faire" >&2 ;; esac
    done
  fi
}

identity_pass
# Requêtes arrivées pendant la passe (#23 : dongles réapparus à quelques secondes d'écart) : le .path ne relance pas une
# unité encore active, on relit donc le fichier et on traite tout de suite les MAC nouvelles. Borné : au plus REREAD_MAX
# passes complémentaires, chacune limitée aux MAC jamais vues dans cette exécution ; jamais de boucle.
if [ -n "$REQUESTS" ] && [ "$RESET" != 1 ]; then
  DONE_MACS="$ONLY" reread=0
  while :; do
    ONLY=""
    read_requests "$REQUESTS" quiet
    NEW=""
    for mac in $ONLY; do case " $DONE_MACS " in *" $mac "*) ;; *) NEW="${NEW:+$NEW }$mac" ;; esac; done
    [ -n "$NEW" ] || break
    if [ "$reread" -ge "$REREAD_MAX" ]; then
      echo "btmux-adapters: AVERTISSEMENT $REQUESTS : borne de $REREAD_MAX relecture(s) atteinte — ${NEW// /, } laissée(s) à la requête suivante" >&2
      break
    fi
    reread=$((reread + 1))
    log "relecture $reread/$REREAD_MAX de $REQUESTS : requête(s) arrivée(s) pendant la passe"
    ONLY="$NEW" DONE_MACS="$DONE_MACS $NEW"
    identity_pass
  done
fi
exit 0
