/**
 * Notifications : être prévenu quand un agent a besoin de vous.
 *
 * Un petit panneau sous la cloche de l'en-tête, comme « Affichage ». Tout y
 * tient en quatre gestes : activer cet appareil, choisir ce qui compte,
 * régler les heures calmes, essayer. Rien ne se demande au navigateur avant
 * que la personne n'ait activé l'interrupteur — une permission réclamée au
 * chargement de la page se refuse, et ne se redemande plus.
 */

import * as api from "../api.js";
import {
  cleVersOctets,
  nomDeLAppareil,
  resumeDesHeuresCalmes,
  situation,
} from "../services/notifications.js";

/** Un élément DOM, en une ligne. */
function el(nom, classe, texte) {
  const e = document.createElement(nom);
  if (classe) e.className = classe;
  if (texte !== undefined) e.textContent = texte;
  return e;
}

function caseACocher(libelle, coche, onChange, { desactivee = false, id = "" } = {}) {
  const label = el("label", "case");
  const input = el("input");
  input.type = "checkbox";
  input.checked = Boolean(coche);
  input.disabled = desactivee;
  if (id) input.id = id;
  input.addEventListener("change", () => onChange(input.checked, input));
  label.append(input, document.createTextNode(" "), el("span", "", libelle));
  return label;
}

/**
 * @param {object} ctx
 * @param {() => string} ctx.token
 * @param {(msg: string) => void} ctx.erreur
 */
export function createNotifications(ctx) {
  const $ = (id) => document.getElementById(id);
  let etat = null; // ce que le service a rendu (`/v1/push/etat`)
  let abonnement = null; // l'inscription de cet appareil, si elle existe
  let retour = ""; // le résultat du dernier essai
  let installation = null; // `beforeinstallprompt`, quand le navigateur le propose
  let occupe = false;

  const supporte = () =>
    "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const ios = () => /iPhone|iPad|iPod/i.test(navigator.userAgent || "");
  const installee = () =>
    window.matchMedia?.("(display-mode: standalone)")?.matches === true || navigator.standalone === true;

  async function enregistrerLeWorker() {
    if (!("serviceWorker" in navigator)) return null;
    try {
      return await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    } catch {
      return null;
    }
  }

  async function inscriptionLocale() {
    if (!supporte()) return null;
    try {
      const registre = (await navigator.serviceWorker.getRegistration("/")) || (await enregistrerLeWorker());
      return registre ? await registre.pushManager.getSubscription() : null;
    } catch {
      return null;
    }
  }

  async function relire() {
    try {
      etat = await api.pushEtat(ctx.token());
    } catch (e) {
      etat = null;
      ctx.erreur(`Notifications : ${e?.message || e}`);
    }
    abonnement = await inscriptionLocale();
    // Une inscription qui existe ici mais que le service a perdue (volume
    // restauré, appareil retiré ailleurs) se rétablit d'elle-même.
    if (etat?.disponible && abonnement && Notification.permission === "granted") {
      try {
        await api.pushAbonner(ctx.token(), abonnement.toJSON(), nomDeLAppareil(navigator.userAgent));
      } catch {
        /* l'écran le dira à l'essai */
      }
    }
  }

  async function activer() {
    if (occupe) return;
    occupe = true;
    retour = "";
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") return;
      const registre = (await enregistrerLeWorker()) && (await navigator.serviceWorker.ready);
      if (!registre) throw new Error("le service d’arrière-plan n’a pas démarré");
      const existante = await registre.pushManager.getSubscription();
      const inscription =
        existante ||
        (await registre.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: cleVersOctets(etat?.cle_publique),
        }));
      await api.pushAbonner(ctx.token(), inscription.toJSON(), nomDeLAppareil(navigator.userAgent));
    } catch (e) {
      ctx.erreur(`Notifications non activées : ${e?.message || e}`);
    } finally {
      occupe = false;
      await relire();
      dessiner();
    }
  }

  async function desactiver() {
    if (occupe) return;
    occupe = true;
    retour = "";
    try {
      const inscription = await inscriptionLocale();
      if (inscription) {
        const endpoint = inscription.endpoint;
        await inscription.unsubscribe();
        await api.pushDesabonner(ctx.token(), { endpoint });
      }
    } catch (e) {
      ctx.erreur(`Notifications non désactivées : ${e?.message || e}`);
    } finally {
      occupe = false;
      await relire();
      dessiner();
    }
  }

  async function regler(patch) {
    try {
      const rendu = await api.pushPreferences(ctx.token(), patch);
      etat = { ...(etat || {}), preferences: rendu.preferences };
    } catch (e) {
      ctx.erreur(`Réglage non enregistré : ${e?.message || e}`);
      await relire();
    }
    dessiner();
  }

  async function essayer() {
    if (occupe) return;
    occupe = true;
    retour = "Envoi en cours…";
    dessiner();
    try {
      const r = await api.pushEssai(ctx.token());
      retour = r.message || (r.ok ? "Envoyé." : "Rien n’a pu être envoyé.");
    } catch (e) {
      retour = `L’essai a échoué : ${e?.message || e}`;
    } finally {
      occupe = false;
      dessiner();
    }
  }

  async function retirer(id) {
    try {
      await api.pushDesabonner(ctx.token(), { id });
    } catch (e) {
      ctx.erreur(`Appareil non retiré : ${e?.message || e}`);
    }
    await relire();
    dessiner();
  }

  async function installer() {
    if (!installation) return;
    installation.prompt();
    try {
      await installation.userChoice;
    } catch {
      /* refusé : rien à faire */
    }
    installation = null;
    dessiner();
  }

  // -- le dessin ----------------------------------------------------------

  function dessiner() {
    const zone = $("notifs-contenu");
    if (!zone) return;
    zone.replaceChildren();
    if (!etat) {
      zone.append(el("p", "popover-note", "Lecture des réglages…"));
      return;
    }
    const prefs = etat.preferences || { categories: {}, calme: {}, detail: true };
    const ici = situation({
      serveur: Boolean(etat.disponible),
      supporte: supporte(),
      ios: ios(),
      installee: installee(),
      permission: supporte() ? Notification.permission : "denied",
      abonne: Boolean(abonnement),
    });

    // 1. Cet appareil
    const entete = el("div", "notifs-appareil");
    const peutBasculer = ici.etat === "inactif" || ici.etat === "actif";
    entete.append(
      caseACocher(
        "Me prévenir sur cet appareil",
        ici.etat === "actif",
        (voulu) => (voulu ? activer() : desactiver()),
        { desactivee: !peutBasculer || occupe, id: "notifs-activer" }
      ),
      el("p", `popover-note notifs-situation notifs-${ici.etat}`, ici.message)
    );
    zone.append(entete);

    if (installation) {
      const b = el("button", "ghost btn-sm", "Installer l’Atelier sur cet appareil");
      b.type = "button";
      b.addEventListener("click", installer);
      zone.append(b);
    }

    if (ici.etat !== "actif") return;

    // 2. Ce qui compte
    const choix = el("fieldset", "notifs-choix");
    choix.append(el("legend", "", "Me prévenir quand"));
    for (const c of etat.categories || []) {
      choix.append(
        caseACocher(c.libelle, prefs.categories?.[c.id], (voulu) =>
          regler({ categories: { [c.id]: voulu } })
        )
      );
    }
    zone.append(choix);

    // 3. Heures calmes
    const calme = el("fieldset", "notifs-calme");
    calme.append(el("legend", "", "Heures calmes"));
    calme.append(
      caseACocher("Ne pas faire de bruit la nuit", prefs.calme?.actif, (voulu) =>
        regler({ calme: { actif: voulu } })
      )
    );
    if (prefs.calme?.actif) {
      const plage = el("div", "notifs-plage");
      for (const [cle, libelle] of [["de", "De"], ["a", "à"]]) {
        const l = el("label", "notifs-heure");
        const input = el("input");
        input.type = "time";
        input.value = prefs.calme[cle] || "";
        input.addEventListener("change", () => input.value && regler({ calme: { [cle]: input.value } }));
        l.append(el("span", "", `${libelle} `), input);
        plage.append(l);
      }
      calme.append(plage, el("p", "popover-note", resumeDesHeuresCalmes(prefs.calme)));
    }
    zone.append(calme);

    // 4. Discrétion
    zone.append(
      caseACocher(
        "Montrer ce que l’agent demande sur l’écran verrouillé",
        prefs.detail,
        (voulu) => regler({ detail: voulu })
      )
    );

    // 5. Essayer
    const essai = el("div", "notifs-essai");
    const b = el("button", "ghost btn-sm", "Envoyer un essai");
    b.type = "button";
    b.disabled = occupe;
    b.addEventListener("click", essayer);
    essai.append(b, el("span", "popover-note notifs-retour", retour));
    zone.append(essai);

    // 6. Les appareils
    const appareils = etat.appareils || [];
    if (appareils.length) {
      const liste = el("ul", "notifs-appareils");
      for (const a of appareils) {
        const li = el("li");
        li.append(el("span", "", a.appareil));
        const r = el("button", "ghost btn-sm", "Retirer");
        r.type = "button";
        r.addEventListener("click", () => retirer(a.id));
        li.append(r);
        liste.append(li);
      }
      zone.append(el("p", "popover-sous-titre", "Appareils prévenus"), liste);
    }
  }

  // -- ouvrir, fermer -----------------------------------------------------

  const ouvert = () => !$("notifs")?.hidden;

  async function basculer(ouvrir) {
    const panneau = $("notifs");
    const bouton = $("btn-notifs");
    if (!panneau || !bouton) return;
    const voulu = ouvrir ?? panneau.hidden;
    panneau.hidden = !voulu;
    bouton.setAttribute("aria-expanded", voulu ? "true" : "false");
    if (voulu) {
      dessiner();
      await relire();
      dessiner();
      $("notifs-activer")?.focus();
    }
  }

  function fermer({ rendreLeFocus = false } = {}) {
    if (!ouvert()) return;
    basculer(false);
    if (rendreLeFocus) $("btn-notifs")?.focus();
  }

  function bind() {
    $("btn-notifs")?.addEventListener("click", (e) => {
      e.stopPropagation();
      basculer();
    });
    $("notifs")?.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        fermer({ rendreLeFocus: true });
      }
    });
    document.addEventListener("click", (e) => {
      const zone = $("notifs-zone");
      if (ouvert() && zone && !zone.contains(e.target)) fermer();
    });
    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      installation = e;
      if (ouvert()) dessiner();
    });
    // Le service worker est posé dès l'entrée : la cloche n'a plus qu'à s'abonner.
    enregistrerLeWorker();
  }

  return { bind, fermer, basculer, relire };
}
