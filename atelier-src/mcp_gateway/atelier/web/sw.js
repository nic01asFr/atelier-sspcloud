/**
 * Le service worker de l'Atelier : les notifications, et rien d'autre.
 *
 * Il n'a pas de cache : pas de mode hors ligne à maintenir, donc pas de page
 * périmée à servir. Il ne lit ni cookie ni clé — la réponse donnée depuis une
 * notification porte un jeton qui ne vaut que pour **cette** question
 * (voir `push.py`).
 *
 * Trois gestes :
 *  - `push` : afficher ce que l'Atelier envoie ; une question déjà tranchée
 *    ailleurs remplace sa notification par un mot, qui se retire seul ;
 *  - `notificationclick` sur « Autoriser » ou « Refuser » : répondre sans ouvrir
 *    l'application ;
 *  - `notificationclick` ailleurs : ouvrir l'application sur la bonne
 *    conversation.
 */

const ICONE = "/icons/icon-192.png";
const LIBELLES = { allow: "Autoriser", deny: "Refuser" };
const DUREE_DU_MOT_MS = 3000;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

function lireLaCharge(event) {
  if (!event.data) return {};
  try {
    return event.data.json();
  } catch {
    return { titre: "Atelier", corps: event.data.text() };
  }
}

/** Affiche un mot, puis le retire : Chrome veut une notification visible par push. */
async function direUnMot(titre, corps, tag) {
  await self.registration.showNotification(titre, {
    body: corps,
    tag,
    icon: ICONE,
    silent: true,
    requireInteraction: false,
  });
  await new Promise((resolu) => setTimeout(resolu, DUREE_DU_MOT_MS));
  const restantes = await self.registration.getNotifications({ tag });
  for (const n of restantes) n.close();
}

async function afficher(charge) {
  if (charge.resolue) {
    return direUnMot(charge.titre || "Atelier", charge.corps || "", charge.tag || "atelier");
  }
  const actions = (charge.actions || [])
    .filter((a) => LIBELLES[a])
    .map((a) => ({ action: a, title: LIBELLES[a] }));
  return self.registration.showNotification(charge.titre || "Atelier", {
    body: charge.corps || "",
    tag: charge.tag || "atelier",
    icon: ICONE,
    badge: ICONE,
    silent: Boolean(charge.silencieux),
    // Une demande d'accord reste affichée jusqu'à ce qu'on y touche : elle
    // attend vraiment quelqu'un.
    requireInteraction: Boolean(charge.decision),
    actions,
    data: { url: charge.url || "/", decision: charge.decision || null, tag: charge.tag || "" },
  });
}

self.addEventListener("push", (event) => {
  event.waitUntil(afficher(lireLaCharge(event)));
});

async function ouvrir(adresse) {
  const cible = new URL(adresse || "/", self.location.origin).href;
  const fenetres = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  for (const fenetre of fenetres) {
    if ("focus" in fenetre) {
      await fenetre.focus();
      if ("navigate" in fenetre) {
        try {
          await fenetre.navigate(cible);
        } catch {
          /* page d'une autre origine, ou déjà fermée : on garde celle-ci */
        }
      }
      return;
    }
  }
  await self.clients.openWindow(cible);
}

async function repondre(donnees, choix) {
  const decision = donnees.decision;
  try {
    const reponse = await fetch(
      `/v1/decisions/${encodeURIComponent(decision.id)}/notification`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jeton: decision.jeton, decision: choix }),
      }
    );
    if (!reponse.ok) throw new Error(String(reponse.status));
  } catch {
    // Pas de réseau, jeton périmé, question déjà tranchée : la carte de la
    // question dit où en sont les choses.
    await ouvrir(donnees.url);
    return;
  }
  try {
    await direUnMot(
      choix === "allow" ? "Autorisé" : "Refusé",
      choix === "allow" ? "L’agent reprend son travail." : "L’agent en est informé.",
      donnees.tag || `decision-${decision.id}`
    );
  } catch {
    /* le mot de confirmation est un confort : la réponse, elle, est donnée */
  }
}

self.addEventListener("notificationclick", (event) => {
  const notification = event.notification;
  const donnees = notification.data || {};
  notification.close();
  if ((event.action === "allow" || event.action === "deny") && donnees.decision?.jeton) {
    event.waitUntil(repondre(donnees, event.action));
    return;
  }
  event.waitUntil(ouvrir(donnees.url));
});
