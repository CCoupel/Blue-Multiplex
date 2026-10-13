# Memoire projet — Blue-Multiplex

> Source de verite unique au demarrage d'une session (/start-session). Mise a jour par /end-session.

## Etat courant

- **Version** : 0.1.0
- **Branche** : main
- **Travail en cours** : aucun — projet initialise par /init-project (2026-10-13), aucun code encore
- **Issues actives** : aucune
- **Prochaine etape suggeree** : milestone v0.1.0 = phase 0 (exploration technique : double role HFP, restriction des profils par adaptateur, pilotage PipeWire pw-* vs Lua, mesure de latence), avant tout developpement

## Regles critiques

- Aucun logiciel ni configuration cote sources (PC pro verrouille) — le Pi doit etre un casque Bluetooth generique.
- Les adaptateurs sont identifies par adresse MAC, jamais par hci0/hci1.
- Tests `hardware` (BlueZ/PipeWire reels) : sur le Pi de qualif uniquement, jamais en CI.

## Corrections de comportement

(aucune pour le moment)
