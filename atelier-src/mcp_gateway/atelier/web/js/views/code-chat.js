/** Vue Code — barre session, fil de chat, composer. */

import { rendreNoteDuMode } from "../ui/mode-processus.js";
import * as api from "../api.js";
import * as S from "../state.js";
import { $ } from "../core/dom.js";
import { appendMessageBody, replierLesResultats, texteDeLaReponse } from "../ui/message-render.js";
import { icone } from "../ui/icones.js";
import { LIBELLES as LIBELLES_ASSISTANT } from "./assistant.js";
import { marquerNonVerifie, nonVerifie } from "./assistant-cartes.js";

/**
 * L'heure d'un message : « 14:05 » le jour même, « 26/09 14:05 » avant.
 *
 * @param {string | number | undefined} quand ISO ou millisecondes
 * @param {Date} [maintenant]
 */
export function heureDuMessage(quand, maintenant = new Date()) {
  if (!quand) return "";
  const d = new Date(quand);
  if (Number.isNaN(d.getTime())) return "";
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const memeJour =
    d.getFullYear() === maintenant.getFullYear()
    && d.getMonth() === maintenant.getMonth()
    && d.getDate() === maintenant.getDate();
  if (memeJour) return `${hh}:${mm}`;
  const jj = String(d.getDate()).padStart(2, "0");
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  return `${jj}/${mo} ${hh}:${mm}`;
}

/** Qui parle, pour un lecteur d'écran : le fil le montre par la mise en page. */
export function nomDeLOrateur(role, assistant) {
  if (role === "user") return "Vous";
  if (role === "assistant") return assistant ? "Assistant" : "Claude";
  if (role === "error") return "Erreur";
  return "";
}

/** La question de la personne à laquelle répond le message de ce rang. */
export function questionPrecedente(messages, rang) {
  for (let i = rang - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (m?.role === "user") return typeof m.rang === "number" && (m.text || "").trim() ? m : null;
  }
  return null;
}

/**
 * @param {object} ctx
 * @param {ReturnType<typeof S.createState>} ctx.state
 * @param {() => void} ctx.render
 */
/** Le fil sans les demandes classées ; une carte vidée disparaît. */
export function retirerLesClassees(messages, classees) {
  return (messages || [])
    .map((m) => ({
      ...m,
      blocks: (m.blocks || [])
        .map((b) =>
          b.type === "perimees" ? { ...b, demandes: (b.demandes || []).filter((d) => !classees.has(d.request_id)) } : b
        )
        .filter((b) => b.type !== "perimees" || b.demandes.length),
    }))
    .filter((m) => m.role !== "system" || m.blocks.length || m.text);
}

/**
 * Le lien « VS Code » de la barre de conversation. Il ouvre **la conversation
 * courante** dans code-server, ou n'existe pas : jamais celle d'avant. Pour un
 * projet comme pour l'Assistant, la porte `/v1/vscode/open` retrouve le dossier
 * et l'identifiant du CLI par la fiche de la conversation.
 */
export function lienVsCode({ vscodeUrl, sessionId, slug, titre }) {
  if (!vscodeUrl || !sessionId) return { hidden: true, href: "", title: "" };
  return { hidden: false, href: api.vscodeOpenUrl(slug, sessionId), title: titre || slug || "" };
}

function poserLienVsCode(etat) {
  const lien = $("session-vscode-link");
  if (!lien) return;
  lien.hidden = etat.hidden;
  if (etat.hidden) {
    lien.removeAttribute("href");
    return;
  }
  lien.href = etat.href;
  lien.title = etat.title;
}

export function createCodeChatView(ctx) {
  const { state, render, composerInput, actions } = ctx;

  // Marge sous laquelle on considère que le lecteur est « en bas ». Assez
  // large pour absorber une ligne qui s'ajoute, assez étroite pour ne pas
  // rattraper quelqu'un qui a délibérément remonté.
  const MARGE_BAS = 80;
// Plus grand que tout fil concevable : le navigateur ramène au maximum réel.
const BAS_DU_FIL = 1e9;

  /**
   * Corriger une question, puis repartir d'elle.
   *
   * On ne réécrit pas le passé : une session Claude ne se rembobine pas. Le
   * serveur ouvre une conversation qui reprend celle-ci jusqu'avant ce
   * message, et la version corrigée y est envoyée. L'originale reste intacte,
   * et le fil qu'on lit continue bien à partir d'ici.
   */
  function ouvrirEdition(div, m, texte) {
    if (div.querySelector(".msg-edition")) return;
    const zone = document.createElement("div");
    zone.className = "msg-edition";
    const champ = document.createElement("textarea");
    champ.className = "msg-edition-champ";
    champ.value = texte;
    champ.rows = Math.min(8, texte.split("\n").length + 1);
    const barre = document.createElement("div");
    barre.className = "msg-actions";

    const valider = document.createElement("button");
    valider.type = "button";
    valider.className = "msg-action";
    valider.textContent = "Reprendre ici";
    valider.addEventListener("click", () => {
      const nouveau = champ.value.trim();
      if (!nouveau) return;
      actions?.reprendreIci?.(m.rang, nouveau);
    });

    const annuler = document.createElement("button");
    annuler.type = "button";
    annuler.className = "msg-action";
    annuler.textContent = "Annuler";
    annuler.addEventListener("click", () => zone.remove());

    champ.addEventListener("keydown", (e) => {
      if (e.key === "Escape") zone.remove();
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        valider.click();
      }
    });

    barre.append(valider, annuler);
    zone.append(champ, barre);
    div.appendChild(zone);
    champ.focus();
    champ.select();
  }

  /**
   * Les gestes qu'on peut faire d'un message, discrètement.
   *
   * On ne pouvait rien en faire : ni copier une réponse — le geste le plus
   * attendu d'une interface conversationnelle — ni reposer une question quand
   * un tour avait échoué.
   *
   * Corriger un message déjà envoyé n'y figure pas, et ce n'est pas un oubli :
   * une session Claude ne se rembobine pas, il faudrait la forker. Offrir la
   * correction serait mentir sur ce qui se passe.
   */
  function boutonAction(nomIcone, libelle, titre) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "msg-action";
    b.title = titre;
    const dit = document.createElement("span");
    dit.textContent = libelle;
    b.append(icone(nomIcone), dit);
    return b;
  }

  /**
   * Le pied d'un message : l'heure, puis les gestes.
   *
   * Pour une réponse de l'agent : « Copier » (la réponse seule, sans la
   * narration des étapes) et « Relancer » (reposer la même question dans une
   * conversation qui reprend d'avant elle — une session Claude ne se
   * rembobine pas, voir « Modifier »). Pour un message de la personne :
   * « Copier » et « Modifier ».
   */
  function renderMessageActions(div, m, rang) {
    const role = m.role || "";
    const texte = role === "assistant" ? texteDeLaReponse(m) : (m.text || "").trim();
    if (m.streaming || (!texte && role !== "user")) return;

    const barre = document.createElement("div");
    barre.className = "msg-actions";

    const heure = heureDuMessage(m.horodatage);
    if (heure) {
      const t = document.createElement("time");
      t.className = "msg-heure";
      t.textContent = heure;
      if (m.horodatage) t.setAttribute("datetime", new Date(m.horodatage).toISOString());
      barre.appendChild(t);
    }

    const copier = boutonAction("copier", "Copier", role === "assistant" ? "Copier la réponse" : "Copier le texte du message");
    copier.addEventListener("click", async () => {
      const dit = copier.querySelector("span:last-child");
      try {
        await navigator.clipboard.writeText(texte);
        if (dit) dit.textContent = "Copié";
        setTimeout(() => {
          if (dit) dit.textContent = "Copier";
        }, 1500);
      } catch {
        S.setError(state, "Copie refusée par le navigateur.");
        render();
      }
    });
    barre.appendChild(copier);

    if (role === "user" && texte && typeof m.rang === "number") {
      const modifier = boutonAction("crayon", "Modifier", "Corriger cette question et repartir d’ici");
      modifier.disabled = !!state.busy;
      modifier.addEventListener("click", () => ouvrirEdition(div, m, texte));
      barre.appendChild(modifier);
    }

    if (role === "assistant") {
      const question = questionPrecedente(state.messages || [], rang);
      if (question) {
        const relancer = boutonAction(
          "relancer",
          "Relancer",
          "Reposer la même question dans une nouvelle conversation qui reprend d’avant elle"
        );
        relancer.disabled = !!state.busy;
        relancer.addEventListener("click", () => {
          relancer.disabled = true;
          actions?.reprendreIci?.(question.rang, question.text.trim());
        });
        barre.appendChild(relancer);
      }
    }

    div.appendChild(barre);
  }

  // Une réponse en cours appelle le rendu des centaines de fois — mesuré : 269
  // fragments pour une seule réponse. Or chaque rendu reconstruit le fil puis
  // lit `scrollHeight`, ce qui force une mise en page synchrone de tout
  // l'arbre. Mesuré à la trace : 2 968 ms de mise en page bloquante pour une
  // seule réponse sur 33 messages, et l'onglet se fige sur une conversation
  // plus longue.
  //
  // On ne rend donc qu'une fois par image d'écran. Les appels intermédiaires
  // se fondent dans celui qui vient, et le navigateur retrouve la main entre
  // deux.
  let renduEnAttente = false;

  function renderThread() {
    if (renduEnAttente) return;
    renduEnAttente = true;
    requestAnimationFrame(() => {
      renduEnAttente = false;
      const suite = rendreLeFil();
      // Le défilement attend l'image suivante. Écrit dans la foulée, il
      // oblige le navigateur à calculer la mise en page sur-le-champ pour
      // savoir où est le bas ; une image plus tard, elle est déjà faite et
      // l'écriture ne coûte rien.
      if (suite) requestAnimationFrame(suite);
    });
  }

  // Une seule écoute, posée sur le fil et non sur les cartes : le fil est
  // reconstruit à chaque rendu, les cartes ne survivent pas, le conteneur si.
  let ecouteDecisions = false;

  /**
   * Rend la décision au serveur, qui réveille le tour.
   *
   * La carte annonce, elle n'agit pas. Un 409 dit que plus personne
   * n'attendait — tour fini, interrompu, ou service redémarré : on le dit
   * plutôt que de laisser croire qu'on a débloqué quelque chose.
   */
  async function repondre(detail) {
    // Le geste se voit tout de suite : la carte se referme sur ce qu'on a
    // choisi avant même que le service ait répondu. On attendait sa réponse,
    // et le clic sur « Autoriser » restait plusieurs secondes sans effet
    // visible (essais du 26/09) — on recliquait. Un refus du service rouvre
    // la carte et dit pourquoi.
    const avant = etatDecision(detail.requestId);
    marquerDecision(
      detail.requestId,
      detail.decision === "allow" ? "allow" : "deny",
      detail.reponses
    );
    render();
    try {
      await api.repondreDecision(state.token, detail.requestId, {
        decision: detail.decision,
        motif: detail.motif,
        portee: detail.portee,
        reponses: detail.reponses,
      });
    } catch (e) {
      const plusAttendue = /409/.test(e?.message || "");
      // Plus personne n'attend : la carte reste close, c'est la vérité.
      if (!plusAttendue && avant) marquerDecision(detail.requestId, avant);
      S.setError(
        state,
        plusAttendue ? "Ce tour n’attend plus cette décision." : e?.message || "Réponse refusée."
      );
      render();
      return;
    }
    if (!state.busy) await reprendreLesQuestions();
  }

  /** L'état d'une carte de décision du fil, avant qu'on n'y touche. */
  function etatDecision(requestId) {
    for (const m of state.messages || []) {
      for (const b of m.blocks || []) {
        if (b.type === "decision" && b.demande?.request_id === requestId) return b.etat || "en_attente";
      }
    }
    return "";
  }

  /**
   * Classe les demandes d'un tour disparu : un refus rendu à chacune la clôt
   * côté service, et elle ne revient plus à l'ouverture.
   */
  async function classer(requestIds) {
    const classees = new Set();
    for (const id of requestIds) {
      try {
        await api.repondreDecision(state.token, id, { decision: "deny", motif: "classée sans réponse" });
        classees.add(id);
      } catch (e) {
        // Déjà close ailleurs : elle est classée quand même.
        if (/404/.test(e?.message || "") || e?.status === 404) classees.add(id);
      }
    }
    state.messages = retirerLesClassees(state.messages, classees);
    render();
  }

  /** Referme une carte, où qu'elle soit dans le fil. */
  function marquerDecision(requestId, etat, reponses) {
    for (const m of state.messages || []) {
      for (const b of m.blocks || []) {
        if (b.type !== "decision" || b.demande?.request_id !== requestId) continue;
        b.etat = etat;
        // Ce qu'on a répondu se garde avec la carte : sans cela le fil
        // conserverait la question sans sa réponse.
        if (reponses) b.reponses = reponses;
      }
    }
  }

  /**
   * Va chercher les questions posées depuis, quand aucun flux n'écoute.
   *
   * Refuser n'arrête pas l'agent — mesuré : il lit le motif et tente une autre
   * route, donc une autre question. Sans ce rappel, on répondrait une fois
   * puis on regarderait un écran muet pendant que le tour attend.
   */
  async function reprendreLesQuestions() {
    const connues = new Set();
    for (const m of state.messages || []) {
      for (const b of m.blocks || []) {
        if (b.type === "decision" && b.demande?.request_id) connues.add(b.demande.request_id);
      }
    }
    for (let essai = 0; essai < 6; essai += 1) {
      await new Promise((r) => setTimeout(r, 2000));
      let liste;
      try {
        liste = await api.decisionsEnAttente(state.token, state.sessionId);
      } catch {
        return;
      }
      const neuves = (liste?.vives || []).filter((d) => !connues.has(d.request_id));
      if (!neuves.length) continue;
      for (const d of neuves) {
        connues.add(d.request_id);
        S.appendMessage(state, {
          role: "system",
          blocks: [{ type: "decision", demande: d, etat: "en_attente" }],
        });
      }
      render();
      return;
    }
  }

  function rendreLeFil() {
    const thread = $("thread");
    if (!thread) return;
    // Dans le fil de l'Assistant, le résultat brut d'un outil est replié : la
    // carte d'action dit ce qui s'est passé. En Code, seulement s'il est long.
    replierLesResultats(S.estAssistant(state));
    if (!ecouteDecisions) {
      ecouteDecisions = true;
      thread.addEventListener("atelier:decision", (e) => repondre(e.detail));
      thread.addEventListener("atelier:classer", (e) => classer(e.detail?.requestIds || []));
    }
    // Le fil est reconstruit à chaque rendu, et une réponse en cours en
    // déclenche des centaines. Recoller systématiquement en bas rendait toute
    // relecture impossible : on ne suit donc que si l'on suivait déjà.
    const suivait =
      thread.scrollHeight - thread.scrollTop - thread.clientHeight <= MARGE_BAS;
    const position = thread.scrollTop;
    if (state.view !== "code") {
      thread.replaceChildren();
      return;
    }
    if (!state.sessionId) {
      const hint = document.createElement("p");
      hint.className = "empty-hint";
      hint.textContent = S.estAssistant(state)
        ? LIBELLES_ASSISTANT.vide
        : state.pendingProjectSlug
        ? "Écrivez votre premier message pour démarrer la conversation."
        : "Écrivez votre premier message — un projet sera créé pour l’accueillir.";
      thread.replaceChildren(hint);
      return;
    }
    if (!state.messages.length && state.chargementFil === state.sessionId) {
      thread.replaceChildren(squeletteDuFil());
      return;
    }
    if (!state.messages.length) {
      const hint = document.createElement("p");
      hint.className = "empty-hint";
      hint.textContent = "Aucun message pour l’instant : écrivez le premier.";
      thread.replaceChildren(hint);
      return;
    }
    // Pendant une réponse, un seul message change — le dernier. Reconstruire
    // les autres coûte leur rendu markdown et invalide toute la mise en page,
    // pour un résultat identique au caractère près. On garde donc le nœud d'un
    // message dont l'empreinte n'a pas bougé.
    // On reconnaît un message à sa place dans le fil, non à son contenu :
    // un message qui change garde son nœud et se met à jour dedans. Sur son
    // contenu, le moindre changement — un outil qui apparaît, une
    // autorisation qu'on accorde — refaisait tout le message : mesuré, 242
    // blocs de code et 270 000 caractères reconstruits, près de deux
    // secondes de gel. C'était le clignotement.
    const anciens = new Map();
    for (const noeud of [...thread.children]) {
      if (noeud.dataset?.cle) anciens.set(noeud.dataset.cle, noeud);
    }
    const voulus = [];
    state.messages.forEach((m, rang) => {
      const cle = rang + ":" + (m.role || "system");
      const garde = anciens.get(cle);
      const noeud = garde || construireMessage(m, cle, rang);
      if (garde) {
        anciens.delete(cle);
        majMessage(garde, m, rang);
      }
      // L'Assistant qui annonce un résultat sans carte d'action dans le tour.
      marquerNonVerifie(noeud, S.estAssistant(state) && nonVerifie(state.messages, rang));
      voulus.push(noeud);
    });
    // Ce qui attend son tour se montre au bout du fil, à sa place : après ce
    // qui est déjà dit, avant ce qui viendra. Sans cela on écrirait dans le
    // vide, sans savoir si le message a été pris.
    for (const attente of state.enFile || []) {
      const cle = "file:" + (attente.id || attente.texte.slice(0, 24));
      const garde = anciens.get(cle);
      if (garde) {
        anciens.delete(cle);
        voulus.push(garde);
        continue;
      }
      voulus.push(construireEnAttente(attente, cle));
    }
    thread.replaceChildren(...voulus);
    // On rend le geste au lieu de le faire : l'appelant l'exécutera à l'image
    // suivante, quand la mise en page sera déjà calculée.
    return () => {
      thread.scrollTop = suivait ? BAS_DU_FIL : position;
    };
  }

  /** La forme d'un fil qui se charge : deux échanges esquissés, sans texte. */
  function squeletteDuFil() {
    const boite = document.createElement("div");
    boite.className = "fil-squelette";
    boite.setAttribute("role", "status");
    const dit = document.createElement("span");
    dit.className = "sr-only";
    dit.textContent = "Chargement de la conversation…";
    boite.appendChild(dit);
    for (const cote of ["user", "assistant", "user", "assistant"]) {
      const bulle = document.createElement("div");
      bulle.className = `squelette-bulle squelette-${cote}`;
      bulle.setAttribute("aria-hidden", "true");
      for (let i = 0; i < (cote === "user" ? 1 : 3); i += 1) {
        const ligne = document.createElement("span");
        ligne.className = "squelette-ligne";
        bulle.appendChild(ligne);
      }
      boite.appendChild(bulle);
    }
    return boite;
  }

  /**
   * Un message écrit pendant qu'un tour travaille, et qui n'est pas parti.
   *
   * Il s'affiche comme ce qu'il est — la parole de l'utilisateur, en attente —
   * et se retire tant qu'il n'a pas quitté la file. Une fois parti, il devient
   * un message ordinaire : c'est le service qui l'annonce.
   */
  function construireEnAttente(attente, cle) {
    const div = document.createElement("div");
    div.dataset.cle = cle;
    div.className = "msg user msg-en-file";

    const etiquette = document.createElement("span");
    etiquette.className = "role";
    etiquette.textContent = "en attente";
    div.appendChild(etiquette);

    const texte = document.createElement("div");
    texte.className = "msg-text-plain";
    texte.textContent = attente.texte || "";
    div.appendChild(texte);

    const barre = document.createElement("div");
    barre.className = "msg-actions";
    const retirer = document.createElement("button");
    retirer.type = "button";
    retirer.className = "msg-action";
    retirer.textContent = "Retirer";
    retirer.title = "Retirer ce message avant qu'il ne parte";
    retirer.addEventListener("click", () => {
      div.dispatchEvent(
        new CustomEvent("atelier:annuler-file", {
          bubbles: true,
          detail: { id: attente.id },
        })
      );
    });
    barre.appendChild(retirer);
    div.appendChild(barre);
    return div;
  }

  /** Rafraîchit un message sans le refaire : seul ce qui bouge est redessiné. */
  function majMessage(div, m, rang) {
    div.classList.toggle("msg-streaming", !!m.streaming);
    appendMessageBody(div, m);
    // Le pied se reconstruit, sauf s'il n'a pas bougé : c'est lui qu'on
    // survole, et un bouton remplacé sous le pointeur perdait son clic.
    const cleDuPied = [m.streaming ? 1 : 0, state.busy ? 1 : 0, m.horodatage || "", (m.text || "").length].join(":");
    const pied = div.querySelector(":scope > .msg-actions");
    if (pied && pied.dataset.cle === cleDuPied) return;
    pied?.remove();
    renderMessageActions(div, m, rang);
    const neuf = div.querySelector(":scope > .msg-actions");
    if (neuf) neuf.dataset.cle = cleDuPied;
  }

  function construireMessage(m, cle, rang) {
    const div = document.createElement("div");
    div.dataset.cle = cle;
    const role = m.role || "system";
    div.className = `msg ${role === "user" ? "user" : role === "assistant" ? "assistant" : role === "error" ? "error-msg" : role === "tool" ? "tool" : "system"}`;
    if (m.streaming) div.classList.add("msg-streaming");
    // Qui parle se voit à la mise en page (la personne à droite, l'agent à
    // gauche) ; on le dit quand même, en toutes lettres, au lecteur d'écran.
    // Une erreur, elle, s'annonce aussi à l'œil.
    const nom = nomDeLOrateur(role, S.estAssistant(state));
    if (nom) {
      const label = document.createElement("span");
      label.className = role === "error" ? "role" : "role sr-only";
      label.textContent = nom;
      div.appendChild(label);
    }
    appendMessageBody(div, m);
    renderMessageActions(div, m, rang);
    const pied = div.querySelector(":scope > .msg-actions");
    if (pied) pied.dataset.cle = [m.streaming ? 1 : 0, state.busy ? 1 : 0, m.horodatage || "", (m.text || "").length].join(":");
    return div;
  }

  function renderComposer() {
    const sessionReady = state.view === "code" && !!state.token;
    // On écrit même pendant un tour : le message attend son tour au lieu
    // d'être refusé. Seul le premier message d'une conversation neuve doit
    // attendre, faute de conversation où le déposer.
    const canSend = sessionReady && (!state.busy || !!state.sessionId);
    const input = $("composer-input");
    const send = $("btn-send");
    const stop = $("btn-stop");
    const attach = $("btn-composer-attach");
    const attachInput = $("composer-attach-input");
    const hasContent =
      !!input?.value.trim() || (state.composerAttachments?.length > 0);
    if (input) {
      input.disabled = !canSend;
      input.placeholder = S.estAssistant(state) ? LIBELLES_ASSISTANT.composeur : "Message Claude Code…";
    }
    if (send) {
      send.disabled = !canSend || !hasContent;
      // Il reste visible pendant un tour : c'est par lui qu'on met en file.
      send.hidden = false;
      send.textContent = state.busy ? "Mettre en file" : "Envoyer";
    }
    if (stop) stop.hidden = !state.busy;
    // Avant le premier message, il n'y a pas encore de conversation où les
    // déposer : elles attendent côté écran, et partent dès que la conversation
    // naît (voir `assurerConversation`).
    const peutJoindre = sessionReady;
    if (attach) attach.disabled = !peutJoindre;
    if (attachInput) attachInput.disabled = !peutJoindre;

    // Le modèle appartient à la conversation, comme `/model` dans Claude Code :
    // il se choisit avant le premier message (il vaut dès le premier tour) et
    // se change ensuite, pour les tours à venir.
    const modele = $("composer-model");
    if (modele) {
      const courante = state.sessions?.find((x) => x.session_id === state.sessionId);
      const valeur = state.sessionId ? courante?.model || "" : state.modeleEnAttente || "";
      composerInput?.remplirLesModeles?.(modele, valeur);
      modele.disabled = !sessionReady || state.busy;
      modele.hidden = !sessionReady;
    }

    // Le mode de travail appartient à la conversation. Il se choisit aussi
    // avant le premier message (lot H : il n'apparaissait qu'après) ; il est
    // alors posé sur la conversation dès qu'elle naît. Il ne vaut que pour les
    // tours à venir, ce que dit l'infobulle.
    const mode = $("composer-mode");
    if (mode) {
      // L'Assistant n'a pas de projet : son défaut ne s'appelle pas ainsi.
      const premier = mode.options?.[0];
      const ditDefaut = S.estAssistant(state) ? "Mode par défaut" : "Défaut du projet";
      if (premier && premier.textContent !== ditDefaut) premier.textContent = ditDefaut;
      const courante = state.sessions?.find((x) => x.session_id === state.sessionId);
      mode.disabled = !sessionReady || state.busy;
      mode.hidden = !sessionReady;
      const valeur = state.sessionId ? courante?.permission_mode || "" : state.modeEnAttente || "";
      if (mode.value !== valeur) mode.value = valeur;
      mode.title = valeur === "plan"
        ? "Plan — l’agent réfléchit et propose, sans rien modifier. S’applique aux tours à venir."
        : valeur === "bypassPermissions"
          ? "Sans garde-fou — l’agent agit sans rien demander, y compris hors du projet. Vaut aussi dans VS Code et au terminal."
          : "Comment l’agent travaille dans ce fil — le même mode dans VS Code et au terminal. S’applique aux tours à venir.";
      mode.classList.toggle("composer-mode-danger", valeur === "bypassPermissions");
    }
    // Ce que vaut le changement de mode : n'est dit que pour la conversation
    // où on l'a fait, et tant qu'on y reste.
    const mp = state.modeProcessus;
    rendreNoteDuMode(
      $("composer-mode-note"),
      sessionReady && mp && mp.sessionId === state.sessionId ? mp.note : null
    );
    const modeProjet = $("btn-mode-projet");
    if (modeProjet) {
      const valeurMode = $("composer-mode")?.value || "";
      modeProjet.hidden = !sessionReady || !valeurMode;
      modeProjet.disabled = state.busy;
    }
    composerInput?.syncGrow?.();
    composerInput?.renderAttachments?.();
  }

  /**
   * Barre de conversation — deux etats sur le meme composant :
   * conversation ouverte (projet fige) ou accueil (projet a choisir).
   */
  function renderSessionBar() {
    const bar = $("session-bar");
    if (!bar) return;
    if (state.view !== "code") {
      bar.hidden = true;
      return;
    }
    bar.hidden = false;

    const enConversation = !!state.sessionId;
    const current = enConversation
      ? state.sessions.find((s) => s.session_id === state.sessionId)
      : null;
    const slug = enConversation
      ? state.slug || current?.slug || ""
      : state.pendingProjectSlug || "";
    const project = state.projects.find((p) => p.slug === slug);

    if (S.estAssistant(state)) {
      // L'Assistant n'a pas de projet à choisir : son nom tient lieu de projet.
      const titreAssistant = current ? S.sessionLabel(current) : LIBELLES_ASSISTANT.nouvelle;
      $("session-title-display").textContent = titreAssistant;
      $("session-title-display").title = titreAssistant;
      const etiquette = $("session-project-label");
      if (etiquette) {
        etiquette.hidden = false;
        etiquette.textContent = LIBELLES_ASSISTANT.titre;
      }
      const choix = $("session-project-select");
      if (choix) choix.hidden = true;
      poserLienVsCode(
        lienVsCode({
          vscodeUrl: state.meta?.vscode_url,
          sessionId: enConversation ? state.sessionId : "",
          slug: current?.slug || slug,
          titre: LIBELLES_ASSISTANT.titre,
        }),
      );
      return;
    }
    const titleEl = $("session-title-display");
    if (titleEl) {
      titleEl.textContent = enConversation
        ? (current ? S.sessionLabel(current) : "Conversation")
        : "Nouvelle conversation";
      // Le titre se tronque sur une ligne : entier au survol.
      titleEl.title = titleEl.textContent;
    }

    // Projet : fige en conversation, choisissable sur l'accueil.
    const projectEl = $("session-project-label");
    const selectEl = $("session-project-select");
    if (projectEl) {
      projectEl.hidden = !enConversation;
      projectEl.textContent = project?.title || slug || "—";
    }
    if (selectEl) {
      selectEl.hidden = enConversation;
      if (!enConversation) {
        const avant = selectEl.value;
        selectEl.innerHTML = "";
        const neuf = document.createElement("option");
        neuf.value = "";
        neuf.textContent = "— créer un projet —";
        selectEl.appendChild(neuf);
        for (const p of S.codeProjects(state)) {
          const opt = document.createElement("option");
          opt.value = p.slug;
          opt.textContent = p.title || p.slug;
          selectEl.appendChild(opt);
        }
        const voulu = state.pendingProjectSlug || "";
        selectEl.value = [...selectEl.options].some((o) => o.value === voulu)
          ? voulu
          : avant && [...selectEl.options].some((o) => o.value === avant)
            ? avant
            : "";
      }
    }

    // L'état et le nombre de tours se lisent déjà dans la liste, en face de
    // chaque conversation ; les répéter ici doublait sans rien apprendre.
    poserLienVsCode(
      lienVsCode({
        vscodeUrl: state.meta?.vscode_url,
        sessionId: enConversation ? state.sessionId : "",
        slug: current?.slug || slug,
        titre: project?.path || slug,
      }),
    );

    // Les créations du projet ne s'ouvrent plus dans un autre onglet : le
    // bouton « Panneau » les montre à côté du fil (voir `views/panneau.js`).
  }

  function renderCodeChat() {
    renderSessionBar();
    renderThread();
    renderComposer();
  }

  return { renderCodeChat, renderThread, renderComposer, renderSessionBar };
}
