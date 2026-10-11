// Les notifications côté navigateur : dire juste ce qu'on sait et ce qu'on ne sait pas.
//
// C'est ici que se joue le « grand public » : une notification qui ne marche pas
// sans qu'on sache pourquoi est pire qu'une absence de notification. Chaque
// situation de l'appareil doit avoir son mot, et le bon.

import { egal, verifier, bilan } from "./verifier.mjs";

import {
  cleVersOctets,
  nomDeLAppareil,
  resumeDesHeuresCalmes,
  situation,
} from "../../mcp_gateway/atelier/web/js/services/notifications.js";

// ── La clé publique, sous la forme que le navigateur attend ──────────────

{
  // 3 octets 0xfb 0xff 0xfe → « -__-  » en base64url, avec les deux alphabets.
  const octets = cleVersOctets("-__-");
  egal(Array.from(octets), [0xfb, 0xff, 0xfe], "l’alphabet base64url se relit (- et _)");
  const sansRemplissage = cleVersOctets("AQID"); // 1 2 3
  egal(Array.from(sansRemplissage), [1, 2, 3], "une clé sans « = » se relit");
  const avecReste = cleVersOctets("AQI"); // 1 2 (remplissage manquant)
  egal(Array.from(avecReste), [1, 2], "le remplissage manquant est rétabli");
  egal(cleVersOctets("").length, 0, "une clé vide ne plante pas");
}

// ── Un nom d'appareil que la personne reconnaît ─────────────────────────

{
  egal(
    nomDeLAppareil("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36"),
    "Android · Chrome",
    "un téléphone Android sous Chrome",
  );
  egal(
    nomDeLAppareil("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1"),
    "iPhone · Safari",
    "un iPhone sous Safari",
  );
  egal(
    nomDeLAppareil("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36 Edg/126.0"),
    "Windows · Edge",
    "Edge se reconnaît avant Chrome, dont il porte le nom",
  );
  egal(nomDeLAppareil(""), "Appareil", "sans indication, un nom neutre");
}

// ── La situation de l'appareil, et le mot juste pour chacune ────────────

const base = { serveur: true, supporte: true, ios: false, installee: false, permission: "default", abonne: false };

{
  egal(situation({ ...base }).etat, "inactif", "au départ : à activer");
  egal(situation({ ...base, permission: "granted", abonne: true }).etat, "actif", "autorisé et inscrit : actif");
  egal(situation({ ...base, permission: "granted", abonne: false }).etat, "inactif", "autorisé mais pas inscrit : à activer");
  const bloque = situation({ ...base, permission: "denied" });
  egal(bloque.etat, "bloque", "refusé dans le navigateur : bloqué");
  verifier(/réglages du navigateur/.test(bloque.message), "le mot dit où lever le blocage");
  egal(situation({ ...base, supporte: false }).etat, "non_supporte", "navigateur sans notifications");
  egal(situation({ ...base, serveur: false }).etat, "indisponible", "service sans notifications");
}

{
  // iPhone : les notifications ne marchent que pour une application ajoutée à
  // l'écran d'accueil. Le dire AVANT de demander une permission qui ne servirait à rien.
  const ios = situation({ ...base, ios: true, installee: false });
  egal(ios.etat, "installer", "iPhone non installé : il faut d’abord l’écran d’accueil");
  verifier(/Sur l’écran d’accueil/.test(ios.message), "le mot dit le geste exact");
  egal(situation({ ...base, ios: true, installee: true }).etat, "inactif", "iPhone installé : on peut activer");
  // Le service sans notifications l'emporte : inutile d'installer quoi que ce soit.
  egal(situation({ ...base, ios: true, serveur: false }).etat, "indisponible", "service indisponible avant tout");
}

// ── Les heures calmes ────────────────────────────────────────────────────

{
  egal(resumeDesHeuresCalmes({ actif: false, de: "22:00", a: "07:00" }), "", "coupées : rien à dire");
  verifier(
    resumeDesHeuresCalmes({ actif: true, de: "22:00", a: "07:00" }).includes("De 22:00 à 07:00"),
    "actives : la plage est dite",
  );
}

bilan("notifications");
