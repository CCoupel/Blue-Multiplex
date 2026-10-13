# Cadrage du site marketing — btmux

> Réponses de cadrage validées le 2026-10-13 (avant toute release). Référence pour l'agent `marketing-release`
> lors de l'initialisation du site : **ne pas reposer ces questions**, partir d'ici et ne demander que ce qui
> manque. Au `PUBLISH` du site, ce cadrage est recopié dans `MARKETING/CADRAGE.md` sur `gh-pages`.
> Emplacement du site : branche `gh-pages` uniquement (worktree `MARKETING/`), GitHub Pages
> `https://ccoupel.github.io/Blue-Multiplex/`, pas de domaine personnalisé.

## Site souhaité

Oui (`marketing.site: auto`).

## Public cible et problème

- **Public** : bricoleurs et télétravailleurs équipés de plusieurs PC (dont un PC pro verrouillé), téléphones et
  casques Bluetooth ; à l'aise avec un Raspberry Pi.
- **Problème** : changer de source audio impose de déconnecter/reconnecter le casque à chaque fois.

## Proposition de valeur

**Accroche** : « Un casque, toutes vos sources. Appairez une fois, basculez en un clic. »

**Trois bénéfices clés** :
1. Zéro réappairage : PC et téléphones voient le Pi comme un casque, les casques le voient comme un téléphone.
2. Compatible avec un PC pro verrouillé : aucun logiciel ni pilote côté sources.
3. Micro et appels inclus : bascule automatique sur appel (HFP), boutons du casque et volume relayés.

## Identité

| Élément | Valeur |
|---------|--------|
| Nom affiché | **btmux** (sous-titre : Blue-Multiplex) |
| Ton | Décontracté, communauté maker ; **tutoiement** en FR |
| Couleurs | Bleu / bleu nuit dominant (« Blue »), accent clair pour les CTA |
| Logo | À créer : logo vectoriel simple (SVG) évoquant deux flux Bluetooth convergeant vers un casque |

## Style

**Produit grand public** : visuels larges, bénéfices avant la technique, puis sections techniques en dessous.
Pas de sites de référence imposés.

## Sections

Obligatoires : **Problématiques**, **Solutions**, **Architecture**.
Souhaitées :
- **Téléchargement / installation** : lien vers la dernière GitHub Release (paquet `.deb`) et procédure d'installation sur le Pi.
- **Matériel requis** : Raspberry Pi 4/5, deux dongles USB Bluetooth 5.x (RTL8761B, ex. TP-Link UB500), rallonges USB, alimentation officielle, Ethernet. Liens non affiliés.
- **Roadmap** : alimentée par les milestones et issues GitHub ouvertes (streaming réseau, LE Audio, mixage multi-sources...).

## Visuels

Pas de photos. Prévoir :
- **Schémas** (SVG inline, bilingues) : architecture sources → `hci-src` → PipeWire → `hci-hp` → casques ; priorité de routage (appel > manuel > dernier flux actif) ; séquence d'appairage.
- **Logo** SVG (voir Identité).
- Placeholders réservés pour de futures photos du montage.

## Appels à l'action

- **Principal** : « Télécharger la dernière version » → page des GitHub Releases
  (`https://github.com/CCoupel/Blue-Multiplex/releases/latest`), qui porte les paquets.
- **Secondaire** : « Voir le code sur GitHub » → `https://github.com/CCoupel/Blue-Multiplex`.
- Liens : dépôt, releases, documentation (`docs/`).

## Langues

FR + EN avec commutateur de langue (FR par défaut).
